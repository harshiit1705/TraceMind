"""Metrics ingestion, persistence, anomaly forwarding, and time-series overview service."""

from datetime import datetime, timedelta, timezone
import math
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.service import Service
from app.models.telemetry import MetricSample
from app.repositories.project_repository import ProjectRepository
from app.repositories.service_repository import ServiceRepository
from app.repositories.telemetry_repository import MetricSampleRepository
from app.schemas.anomaly import AnomalyEvaluationRequest
from app.schemas.telemetry import (
    MetricBatchIngestRequest,
    MetricBatchIngestResponse,
    MetricIngestResultItem,
    MetricSampleResponse,
    TelemetryOverviewResponse,
    TelemetryTimeSeriesPointResponse,
)
from app.services.anomaly.detector import OutOfOrderMeasurementError
from app.services.anomaly.service import AnomalyService, ServiceNotFoundError
from app.services.telemetry.redaction import sanitize_attributes

ELIGIBLE_ANOMALY_METRICS = {"latency", "error_rate", "request_rate"}


class TelemetryProjectNotFoundError(Exception):
    pass


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 2)
    idx = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(idx))
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    val = sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac
    return round(val, 2)


class MetricsService:
    def __init__(self, db: Session):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.service_repo = ServiceRepository(db)
        self.metric_repo = MetricSampleRepository(db)
        self.anomaly_service = AnomalyService(db)

    def ingest_batch(self, request: MetricBatchIngestRequest) -> MetricBatchIngestResponse:
        project = self.project_repo.get_by_id(request.project_id)
        if not project:
            raise TelemetryProjectNotFoundError(f"Project '{request.project_id}' was not found.")

        results: List[MetricIngestResultItem] = []
        accepted_count = 0
        duplicate_count = 0
        anomalies_detected_count = 0

        service_cache: Dict[str, Service] = {}

        for item in request.samples:
            svc = service_cache.get(item.service_identifier)
            if svc is None:
                svc = self.service_repo.get_by_project_and_identifier(
                    project_id=request.project_id,
                    identifier=item.service_identifier,
                )
                if not svc:
                    raise ServiceNotFoundError(
                        f"Service '{item.service_identifier}' was not found in project '{request.project_id}'."
                    )
                service_cache[item.service_identifier] = svc

            # Duplicate check by source_event_id
            if item.source_event_id:
                existing = self.metric_repo.get_by_source_event_id(
                    project_id=request.project_id,
                    service_id=svc.id,
                    metric_name=item.metric_name,
                    source_event_id=item.source_event_id,
                )
                if existing:
                    duplicate_count += 1
                    results.append(
                        MetricIngestResultItem(
                            id=existing.id,
                            service_identifier=item.service_identifier,
                            metric_name=item.metric_name,
                            persisted=False,
                            duplicate=True,
                            anomaly_evaluated=False,
                        )
                    )
                    continue

            svc_id = svc.id
            svc_slug = svc.slug

            ts = item.timestamp or datetime.now(timezone.utc)
            sample_row = MetricSample(
                id=uuid4(),
                project_id=request.project_id,
                service_id=svc_id,
                metric_name=item.metric_name,
                metric_unit=item.metric_unit,
                value=float(item.value),
                timestamp=ts,
                endpoint=item.endpoint,
                http_status_code=item.http_status_code,
                request_id=item.request_id,
                trace_id=item.trace_id,
                source_event_id=item.source_event_id,
                attributes_json=sanitize_attributes(item.attributes),
            )

            try:
                with self.db.begin_nested():
                    self.metric_repo.create(sample_row, commit=False)
                # Update service snapshot fields in the same commit to minimize lock contention
                if item.metric_name == "latency":
                    svc.p95_latency_ms = round(float(item.value), 2)
                elif item.metric_name == "error_rate":
                    svc.error_rate_percent = round(float(item.value), 2)
                    if float(item.value) >= 10.0:
                        svc.status = "degraded"
                    elif svc.status == "degraded" and float(item.value) < 1.0:
                        svc.status = "healthy"
                elif item.metric_name == "request_rate":
                    svc.request_rate_rps = round(float(item.value), 2)
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                duplicate_count += 1
                existing = None
                if item.source_event_id:
                    existing = self.metric_repo.get_by_source_event_id(
                        project_id=request.project_id,
                        service_id=svc_id,
                        metric_name=item.metric_name,
                        source_event_id=item.source_event_id,
                    )
                existing_id = existing.id if existing else None
                results.append(
                    MetricIngestResultItem(
                        id=existing_id,
                        service_identifier=item.service_identifier,
                        metric_name=item.metric_name,
                        persisted=False,
                        duplicate=True,
                    )
                )
                continue

            sample_id = sample_row.id
            accepted_count += 1

            # Forward eligible measurements to existing AnomalyService without double-calling
            anomaly_evaluated = False
            is_anomaly = False
            anomaly_severity = None
            anomaly_note = None

            if item.evaluate_anomaly and item.metric_name in ELIGIBLE_ANOMALY_METRICS:
                try:
                    eval_req = AnomalyEvaluationRequest(
                        project_id=request.project_id,
                        service_identifier=svc_slug,
                        metric_name=item.metric_name,
                        observed_value=float(item.value),
                        timestamp=ts,
                        source_event_id=item.source_event_id,
                    )
                    eval_resp = self.anomaly_service.evaluate_measurement(eval_req)
                    anomaly_evaluated = True
                    is_anomaly = eval_resp.is_anomaly
                    anomaly_severity = eval_resp.severity.value if eval_resp.is_anomaly else None
                    if is_anomaly:
                        anomalies_detected_count += 1
                except OutOfOrderMeasurementError:
                    # Delayed/out-of-order historical sample persisted in MetricSample without corrupting detector
                    anomaly_evaluated = False
                    anomaly_note = "Out-of-order/delayed sample stored without advancing detector watermark."

            results.append(
                MetricIngestResultItem(
                    id=sample_id,
                    service_identifier=item.service_identifier,
                    metric_name=item.metric_name,
                    persisted=True,
                    duplicate=False,
                    anomaly_evaluated=anomaly_evaluated,
                    is_anomaly=is_anomaly,
                    anomaly_severity=anomaly_severity,
                    anomaly_note=anomaly_note,
                )
            )

        return MetricBatchIngestResponse(
            accepted_count=accepted_count,
            duplicate_count=duplicate_count,
            anomalies_detected_count=anomalies_detected_count,
            results=results,
        )

    def query_metrics(
        self,
        project_id: Optional[UUID] = None,
        service_identifier: Optional[str] = None,
        metric_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        trace_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[MetricSampleResponse], int]:
        resolved_service_id: Optional[UUID] = None
        if service_identifier:
            try:
                resolved_service_id = UUID(service_identifier)
            except ValueError:
                if project_id:
                    svc = self.service_repo.get_by_project_and_identifier(project_id, service_identifier)
                    if not svc:
                        return [], 0
                    resolved_service_id = svc.id
                else:
                    svc = self.db.query(Service).filter(
                        (Service.slug == service_identifier) | (Service.identifier == service_identifier)
                    ).first()
                    if not svc:
                        return [], 0
                    resolved_service_id = svc.id

        rows, total = self.metric_repo.query(
            project_id=project_id,
            service_id=resolved_service_id,
            metric_name=metric_name,
            endpoint=endpoint,
            trace_id=trace_id,
            start_time=start_time,
            end_time=end_time,
            skip=skip,
            limit=limit,
        )

        svc_ids = {r.service_id for r in rows}
        svc_map = (
            {s.id: s for s in self.db.query(Service).filter(Service.id.in_(svc_ids)).all()}
            if svc_ids
            else {}
        )

        items: List[MetricSampleResponse] = []
        for r in rows:
            svc = svc_map.get(r.service_id)
            dto = MetricSampleResponse.model_validate(r)
            dto.service_slug = svc.slug if svc else None
            dto.service_name = svc.name if svc else None
            items.append(dto)

        return items, total

    def _baseline_average(self, project_id: UUID, metric_name: str, aggregate: str = "mean") -> Optional[float]:
        baselines = (
            self.db.query(AnomalyBaseline)
            .filter(
                AnomalyBaseline.project_id == project_id,
                AnomalyBaseline.metric_name == metric_name,
            )
            .all()
        )
        baseline_vals: List[float] = []
        for b in baselines:
            state = b.baseline_state or {}
            if "ewma" in state and state["ewma"] is not None:
                baseline_vals.append(float(state["ewma"]))
            elif "values" in state and state["values"]:
                vals = [float(x) for x in state["values"]]
                baseline_vals.append(sum(vals) / len(vals))
        if not baseline_vals:
            return None
        if aggregate == "sum":
            return round(sum(baseline_vals), 2)
        return round(sum(baseline_vals) / len(baseline_vals), 2)

    def get_telemetry_overview(
        self,
        time_range: str = "15m",
        project_id: Optional[UUID] = None,
    ) -> TelemetryOverviewResponse:
        """Compute time-bucketed telemetry overview strictly from persisted MetricSample & AnomalyEvent rows."""
        if project_id is None:
            proj = self.project_repo.get_by_slug("core-ecommerce") or self.project_repo.list_all()[0]
            project_id = proj.id

        range_map = {
            "15m": (timedelta(minutes=15), timedelta(minutes=1)),
            "1h": (timedelta(hours=1), timedelta(minutes=5)),
            "24h": (timedelta(hours=24), timedelta(hours=1)),
        }
        window_delta, bucket_delta = range_map.get(time_range, range_map["15m"])
        effective_range = time_range if time_range in range_map else "15m"

        now_utc = datetime.now(timezone.utc)
        start_utc = now_utc - window_delta

        samples = self.metric_repo.get_window_samples(
            project_id=project_id,
            start_time=start_utc,
            end_time=now_utc,
        )

        anomalies = (
            self.db.query(AnomalyEvent)
            .filter(
                AnomalyEvent.project_id == project_id,
                AnomalyEvent.occurred_at >= start_utc,
                AnomalyEvent.occurred_at <= now_utc,
            )
            .all()
        )

        baseline_p95_ms = self._baseline_average(project_id, "latency", aggregate="mean") or 0.0
        baseline_rps = self._baseline_average(project_id, "request_rate", aggregate="sum")

        if not samples:
            return TelemetryOverviewResponse(
                timeRange=effective_range,
                points=[],
                currentThroughputRps=0.0,
                meanThroughputRps=0.0,
                peakThroughputRps=0.0,
                throughputAvailable=False,
                requestRateStatus="no_traffic",
                totalRequests=0,
                totalMetricSamples=0,
                sampleIngestionRatePerSec=None,
                currentErrorRatePercent=0.0,
                peakErrorRatePercent=0.0,
                currentP95Ms=0.0,
                baselineP95Ms=baseline_p95_ms,
                currentP99Ms=0.0,
            )

        bucket_sec = int(bucket_delta.total_seconds())
        buckets: Dict[int, Dict[str, object]] = {}
        anomaly_buckets: set[int] = set()
        all_sample_timestamps: List[datetime] = []

        def _aware_utc(dt: datetime) -> datetime:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        def _bucket_epoch(dt: datetime) -> int:
            ep = int(_aware_utc(dt).timestamp())
            return (ep // bucket_sec) * bucket_sec

        for s in samples:
            ts_utc = _aware_utc(s.timestamp)
            all_sample_timestamps.append(ts_utc)
            b_ep = _bucket_epoch(ts_utc)
            b = buckets.setdefault(
                b_ep,
                {
                    "latency": [],
                    "latency_statuses": [],
                    "error_rate": [],
                    "svc_windowed": {},
                    "svc_raw_count": {},
                    "svc_rates": {},
                    "req_timestamps": [],
                    "sample_count": 0,
                },
            )
            b["sample_count"] = int(b["sample_count"]) + 1  # type: ignore[arg-type]
            attrs = s.attributes_json or {}
            svc_key = str(s.service_id)

            if s.metric_name == "latency":
                b["latency"].append(float(s.value))  # type: ignore[attr-defined]
                if s.http_status_code is not None:
                    b["latency_statuses"].append(int(s.http_status_code))  # type: ignore[attr-defined]
                b["req_timestamps"].append(ts_utc)  # type: ignore[attr-defined]
            elif s.metric_name == "error_rate":
                req_weight = attrs.get("request_count")
                weight = float(req_weight) if isinstance(req_weight, (int, float)) and req_weight > 0 else 1.0
                b["error_rate"].append((float(s.value), weight))  # type: ignore[attr-defined]
            elif s.metric_name == "request_count":
                cnt_val = max(0.0, float(s.value))
                win_sec = attrs.get("window_seconds")
                if isinstance(win_sec, (int, float)) and float(win_sec) > 0.0:
                    entry = b["svc_windowed"].setdefault(svc_key, {"count": 0.0, "window_sec": 0.0})  # type: ignore[attr-defined]
                    entry["count"] += cnt_val
                    entry["window_sec"] += float(win_sec)
                else:
                    raw_map = b["svc_raw_count"]  # type: ignore[assignment]
                    raw_map[svc_key] = raw_map.get(svc_key, 0.0) + cnt_val  # type: ignore[union-attr]
                b["req_timestamps"].append(ts_utc)  # type: ignore[attr-defined]
            elif s.metric_name == "request_rate":
                rates_map = b["svc_rates"]  # type: ignore[assignment]
                rates_map.setdefault(svc_key, []).append(float(s.value))  # type: ignore[union-attr]
                b["req_timestamps"].append(ts_utc)  # type: ignore[attr-defined]

        for a in anomalies:
            anomaly_buckets.add(_bucket_epoch(a.occurred_at))

        sorted_epochs = sorted(buckets.keys())
        points: List[TelemetryTimeSeriesPointResponse] = []
        total_requests = 0

        for b_ep in sorted_epochs:
            b = buckets[b_ep]
            lat_sorted = sorted(b["latency"])  # type: ignore[arg-type]
            lat_statuses: List[int] = b["latency_statuses"]  # type: ignore[assignment]
            err_vals: List[Tuple[float, float]] = b["error_rate"]  # type: ignore[assignment]
            svc_windowed: Dict[str, Dict[str, float]] = b["svc_windowed"]  # type: ignore[assignment]
            svc_raw_count: Dict[str, float] = b["svc_raw_count"]  # type: ignore[assignment]
            svc_rates: Dict[str, List[float]] = b["svc_rates"]  # type: ignore[assignment]
            req_timestamps: List[datetime] = b["req_timestamps"]  # type: ignore[assignment]
            bucket_samples_count = int(b["sample_count"])  # type: ignore[arg-type]

            windowed_reqs = sum(v["count"] for v in svc_windowed.values())
            raw_count_reqs = sum(svc_raw_count.values())
            if svc_windowed or svc_raw_count:
                bucket_requests = int(round(windowed_reqs + raw_count_reqs))
            else:
                bucket_requests = len(lat_sorted)
            total_requests += bucket_requests

            throughput_available = False
            rps: Optional[float] = None

            if svc_windowed:
                # Exact weighted request rate per service summed across active services
                per_svc_rps = [
                    v["count"] / v["window_sec"]
                    for v in svc_windowed.values()
                    if v["window_sec"] > 0.0
                ]
                if per_svc_rps:
                    rps = round(sum(per_svc_rps), 2)
                    throughput_available = True
            elif svc_rates:
                # Mean reported request_rate per service, summed across services
                per_svc_rps = [
                    sum(vals) / len(vals)
                    for vals in svc_rates.values()
                    if vals
                ]
                if per_svc_rps:
                    rps = round(sum(per_svc_rps), 2)
                    throughput_available = True
            elif bucket_requests > 0 and len(req_timestamps) >= 2:
                span_sec = (max(req_timestamps) - min(req_timestamps)).total_seconds()
                if span_sec >= 1.0:
                    rps = round(bucket_requests / float(bucket_sec), 2)
                    throughput_available = True

            if err_vals:
                weight_sum = sum(w for _, w in err_vals)
                err_pct = round(sum(val * w for val, w in err_vals) / weight_sum, 2) if weight_sum > 0 else 0.0
            elif lat_statuses:
                err_cnt = sum(1 for sc in lat_statuses if sc >= 500)
                err_pct = round((err_cnt / len(lat_statuses)) * 100.0, 2)
            else:
                err_pct = 0.0

            dt_utc = datetime.fromtimestamp(b_ep, tz=timezone.utc)
            points.append(
                TelemetryTimeSeriesPointResponse(
                    time=dt_utc.strftime("%H:%M"),
                    timestamp=b_ep * 1000,
                    throughputRps=rps,
                    baselineThroughputRps=baseline_rps,
                    throughputAvailable=throughput_available,
                    requestCount=bucket_requests,
                    metricSamplesCount=bucket_samples_count,
                    errorRatePercent=err_pct,
                    p50Ms=_percentile(lat_sorted, 50),
                    p90Ms=_percentile(lat_sorted, 90),
                    p95Ms=_percentile(lat_sorted, 95),
                    p99Ms=_percentile(lat_sorted, 99),
                    isAnomaly=(b_ep in anomaly_buckets),
                )
            )

        avail_rps = [float(p.throughputRps) for p in points if p.throughputAvailable and p.throughputRps is not None]
        err_series = [p.errorRatePercent for p in points]
        p95_series = [p.p95Ms for p in points if p.p95Ms > 0]
        p99_series = [p.p99Ms for p in points if p.p99Ms > 0]

        has_any_req_signal = any(p.requestCount > 0 or p.throughputAvailable for p in points)
        if avail_rps:
            req_rate_status = "available"
            throughput_available_overall = True
            current_rps: Optional[float] = avail_rps[-1]
            mean_rps: Optional[float] = round(sum(avail_rps) / len(avail_rps), 2)
            peak_rps: Optional[float] = max(avail_rps)
        elif has_any_req_signal:
            req_rate_status = "insufficient_data"
            throughput_available_overall = False
            current_rps = None
            mean_rps = None
            peak_rps = None
        else:
            req_rate_status = "no_traffic"
            throughput_available_overall = False
            current_rps = 0.0
            mean_rps = 0.0
            peak_rps = 0.0

        total_metric_samples = len(samples)
        sample_ingestion_rate: Optional[float] = None
        if total_metric_samples >= 2 and all_sample_timestamps:
            sample_span = (max(all_sample_timestamps) - min(all_sample_timestamps)).total_seconds()
            if sample_span >= 1.0:
                sample_ingestion_rate = round(total_metric_samples / sample_span, 2)

        return TelemetryOverviewResponse(
            timeRange=effective_range,
            points=points,
            currentThroughputRps=current_rps,
            meanThroughputRps=mean_rps,
            peakThroughputRps=peak_rps,
            throughputAvailable=throughput_available_overall,
            requestRateStatus=req_rate_status,
            totalRequests=total_requests,
            totalMetricSamples=total_metric_samples,
            sampleIngestionRatePerSec=sample_ingestion_rate,
            currentErrorRatePercent=points[-1].errorRatePercent if points else 0.0,
            peakErrorRatePercent=max(err_series) if err_series else 0.0,
            currentP95Ms=p95_series[-1] if p95_series else 0.0,
            baselineP95Ms=baseline_p95_ms,
            currentP99Ms=p99_series[-1] if p99_series else 0.0,
        )
