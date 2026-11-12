"""Multi-signal evidence retrieval across persisted metrics, logs, trace spans, and topology."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.models.telemetry import ApplicationLog, MetricSample, TraceSpan
from app.schemas.correlation import (
    BottleneckSpanEvidence,
    CorrelatedLogHighlight,
    MultiSignalEvidenceSummary,
    MultiSignalTimelineEntry,
    ServiceMetricEvidence,
    SignalCoverageSummary,
)
from app.services.telemetry.redaction import redact_secrets


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 2)
    idx = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(idx))
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return round(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac, 2)


_PATTERN_RULES: List[Tuple[str, re.Pattern[str]]] = [
    ("timeout", re.compile(r"(?i)\b(timeout|timed out|deadline exceeded)\b")),
    (
        "connection_failure",
        re.compile(r"(?i)\b(connection refused|connection pool|connect error|unreachable|bad gateway)\b"),
    ),
    (
        "5xx_error",
        re.compile(r"(?i)\b(500|502|503|504|status 5\d\d|internal server error|gateway error|declined|exception)\b"),
    ),
    ("retry", re.compile(r"(?i)\b(retry|retrying|attempt \d+)\b")),
    ("latency_warning", re.compile(r"(?i)\b(slow request|high latency|latency spike|delayed)\b")),
]

_PROPAGATION_PATTERN = re.compile(
    r"(?i)\b(downstream|upstream call failed|calling|failed with status 502|bad gateway from)\b"
)


def _classify_log_pattern(message: str, exception_type: Optional[str], level: str) -> Optional[str]:
    text = f"{message} {exception_type or ''}"
    for name, regex in _PATTERN_RULES:
        if regex.search(text):
            return name
    if level.upper() in ("ERROR", "CRITICAL"):
        return "other_error"
    return None


@dataclass
class ServiceSignalProfile:
    """Normalized per-service telemetry signal profile used by RootCauseRanker."""

    service_id: UUID
    metric_score: float = 0.0
    has_metric_samples: bool = False
    has_anomalous_metrics: bool = False
    max_metric_deviation_pct: float = 0.0
    earliest_metric_breach_at: Optional[datetime] = None

    log_score: float = 0.0
    has_logs: bool = False
    total_logs_count: int = 0
    error_logs_count: int = 0
    distinct_error_keys: int = 0
    distinct_warning_keys: int = 0
    origin_error_log_count: int = 0
    earliest_error_log_at: Optional[datetime] = None

    trace_score: float = 0.0
    has_traces: bool = False
    participating_anomalous_traces: int = 0
    bottleneck_traces_owned: int = 0
    origin_error_traces_owned: int = 0
    avg_bottleneck_self_time_share: float = 0.0
    max_span_self_time_ms: float = 0.0
    suspected_operation: Optional[str] = None
    earliest_fault_span_at: Optional[datetime] = None

    supporting_items: List[str] = field(default_factory=list)
    neutral_items: List[str] = field(default_factory=list)
    contradictory_items: List[str] = field(default_factory=list)
    referenced_metric_names: List[str] = field(default_factory=list)
    referenced_log_ids: List[str] = field(default_factory=list)
    referenced_trace_ids: List[str] = field(default_factory=list)
    referenced_span_ids: List[str] = field(default_factory=list)


@dataclass
class MultiSignalBundle:
    """Complete multi-signal evidence package and per-service scoring inputs."""

    summary: MultiSignalEvidenceSummary
    service_profiles: Dict[UUID, ServiceSignalProfile]
    has_any_telemetry: bool


class MultiSignalEvidenceRetriever:
    """Retrieves, correlates, deduplicates, and summarizes multi-signal telemetry for a window."""

    WINDOW_PADDING_SECONDS = 60
    BASELINE_LOOKBACK_MINUTES = 15
    MAX_METRIC_SAMPLES = 2000
    MAX_LOGS = 500
    MAX_SPANS = 2000
    MAX_HYDRATED_TRACES = 80
    MAX_HIGHLIGHT_LOGS = 25
    MAX_BOTTLENECK_SPANS = 25
    MAX_TIMELINE_ITEMS = 40

    def __init__(self, db: Session):
        self.db = db

    def retrieve(
        self,
        project_id: UUID,
        window_start: datetime,
        window_end: datetime,
        services_map: Dict[UUID, Service],
        anomaly_events: Optional[List[AnomalyEvent]] = None,
        downstream_map: Optional[Dict[UUID, Set[UUID]]] = None,
        correlation_group_id: Optional[UUID] = None,
        topology_complete: bool = True,
        all_services_map: Optional[Dict[UUID, Service]] = None,
    ) -> MultiSignalBundle:
        """Retrieve bounded multi-signal evidence strictly within project boundaries."""
        w_start = _to_utc(window_start)
        w_end = _to_utc(window_end)
        padded_start = w_start - timedelta(seconds=self.WINDOW_PADDING_SECONDS)
        padded_end = w_end + timedelta(seconds=self.WINDOW_PADDING_SECONDS)
        baseline_start = padded_start - timedelta(minutes=self.BASELINE_LOOKBACK_MINUTES)

        service_lookup = all_services_map or services_map
        service_ids = list(services_map.keys())
        profiles: Dict[UUID, ServiceSignalProfile] = {
            sid: ServiceSignalProfile(service_id=sid) for sid in service_ids
        }
        anomaly_events = anomaly_events or []
        downstream_map = downstream_map or {}

        # --- 1. Persisted Metric Samples & Baselines ---
        metric_samples: List[MetricSample] = []
        baseline_samples: List[MetricSample] = []
        persisted_baselines: Dict[Tuple[UUID, str], float] = {}

        if service_ids:
            metric_samples = (
                self.db.query(MetricSample)
                .filter(
                    MetricSample.project_id == project_id,
                    MetricSample.service_id.in_(service_ids),
                    MetricSample.timestamp >= padded_start,
                    MetricSample.timestamp <= padded_end,
                )
                .order_by(MetricSample.timestamp.asc(), MetricSample.id.asc())
                .limit(self.MAX_METRIC_SAMPLES)
                .all()
            )
            baseline_samples = (
                self.db.query(MetricSample)
                .filter(
                    MetricSample.project_id == project_id,
                    MetricSample.service_id.in_(service_ids),
                    MetricSample.timestamp >= baseline_start,
                    MetricSample.timestamp < padded_start,
                )
                .order_by(MetricSample.timestamp.asc(), MetricSample.id.asc())
                .limit(self.MAX_METRIC_SAMPLES)
                .all()
            )
            for b in (
                self.db.query(AnomalyBaseline)
                .filter(
                    AnomalyBaseline.project_id == project_id,
                    AnomalyBaseline.service_id.in_(service_ids),
                )
                .all()
            ):
                b_mean = (b.baseline_state or {}).get("mean")
                if isinstance(b_mean, (int, float)):
                    persisted_baselines[(b.service_id, b.metric_name)] = float(b_mean)

        metric_summaries = self._analyze_metrics(
            metric_samples=metric_samples,
            baseline_samples=baseline_samples,
            persisted_baselines=persisted_baselines,
            services_map=services_map,
            profiles=profiles,
        )

        # --- 2. Persisted Trace Spans (Parent-Child Exclusive Self-Time) ---
        window_spans: List[TraceSpan] = (
            self.db.query(TraceSpan)
            .filter(
                TraceSpan.project_id == project_id,
                TraceSpan.start_time >= padded_start,
                TraceSpan.start_time <= padded_end,
            )
            .order_by(TraceSpan.start_time.asc(), TraceSpan.id.asc())
            .limit(self.MAX_SPANS)
            .all()
        )
        candidate_trace_ids: List[str] = []
        seen_tids: Set[str] = set()
        for sp in window_spans:
            if (sp.service_id in profiles or sp.status == "error" or (sp.duration_ms or 0.0) >= 350.0) and sp.trace_id not in seen_tids:
                seen_tids.add(sp.trace_id)
                candidate_trace_ids.append(sp.trace_id)
                if len(candidate_trace_ids) >= self.MAX_HYDRATED_TRACES:
                    break

        full_spans: List[TraceSpan] = []
        if candidate_trace_ids:
            full_spans = (
                self.db.query(TraceSpan)
                .filter(
                    TraceSpan.project_id == project_id,
                    TraceSpan.trace_id.in_(candidate_trace_ids),
                )
                .order_by(TraceSpan.start_time.asc(), TraceSpan.id.asc())
                .limit(self.MAX_SPANS)
                .all()
            )

        trace_bottlenecks, total_traces_count, incomplete_traces_count, trace_notes = self._analyze_traces(
            spans=full_spans,
            services_map=service_lookup,
            profiles=profiles,
        )

        # --- 3. Persisted Application Logs ---
        logs_in_window: List[ApplicationLog] = []
        if service_ids:
            logs_in_window = (
                self.db.query(ApplicationLog)
                .filter(
                    ApplicationLog.project_id == project_id,
                    ApplicationLog.service_id.in_(service_ids),
                    ApplicationLog.timestamp >= padded_start,
                    ApplicationLog.timestamp <= padded_end,
                )
                .order_by(ApplicationLog.timestamp.asc(), ApplicationLog.id.asc())
                .limit(self.MAX_LOGS)
                .all()
            )

        log_highlights, total_error_logs = self._analyze_logs(
            logs=logs_in_window,
            services_map=services_map,
            profiles=profiles,
        )

        # --- 4. Contradictions, Neutral & Missing Signals Synthesis ---
        metrics_available = len(metric_samples) > 0
        logs_available = len(logs_in_window) > 0
        traces_available = len(full_spans) > 0
        topology_available = topology_complete

        observed_signals: List[str] = []
        missing_signals: List[str] = []
        if anomaly_events:
            observed_signals.append("anomaly_events")
        if topology_available:
            observed_signals.append("topology")
        else:
            missing_signals.append("complete_dependency_topology")
        if metrics_available:
            observed_signals.append("metrics")
        else:
            missing_signals.append("metrics")
        if logs_available:
            observed_signals.append("logs")
        else:
            missing_signals.append("logs")
        if traces_available:
            observed_signals.append("traces")
        else:
            missing_signals.append("traces")

        global_contradictions: List[str] = []
        global_neutral: List[str] = []
        uncertainty_notes: List[str] = list(trace_notes)

        self._evaluate_cross_signal_alignment(
            services_map=services_map,
            profiles=profiles,
            anomaly_events=anomaly_events,
            metrics_available=metrics_available,
            logs_available=logs_available,
            traces_available=traces_available,
            global_contradictions=global_contradictions,
            global_neutral=global_neutral,
        )

        if missing_signals:
            uncertainty_notes.append(
                f"Unavailable signal families ({', '.join(missing_signals)}) were treated as unobserved without negative score penalty."
            )

        # Identify overall primary suspected operation & affected downstream services
        primary_op: Optional[str] = None
        if trace_bottlenecks:
            ranked_spans = sorted(
                trace_bottlenecks,
                key=lambda b: (b.is_origin_error, b.is_bottleneck, b.self_time_ms),
                reverse=True,
            )
            primary_op = f"{ranked_spans[0].service_name}: {ranked_spans[0].operation_name}"

        top_trace_or_anom_sid: Optional[UUID] = None
        if profiles:
            best_sid = max(
                profiles.keys(),
                key=lambda sid: (
                    profiles[sid].trace_score,
                    profiles[sid].log_score,
                    profiles[sid].metric_score,
                ),
            )
            if profiles[best_sid].trace_score > 0 or profiles[best_sid].log_score > 0:
                top_trace_or_anom_sid = best_sid

        affected_downstream: List[str] = []
        if top_trace_or_anom_sid and downstream_map:
            affected_downstream = sorted(
                services_map[cid].name
                for cid in downstream_map.get(top_trace_or_anom_sid, set())
                if cid in services_map and cid != top_trace_or_anom_sid
            )

        # --- 5. Multi-Signal Chronological Timeline ---
        timeline = self._build_timeline(
            anomaly_events=anomaly_events,
            metric_summaries=metric_summaries,
            log_highlights=log_highlights,
            trace_bottlenecks=trace_bottlenecks,
            services_map=services_map,
        )

        coverage = SignalCoverageSummary(
            metrics_available=metrics_available,
            logs_available=logs_available,
            traces_available=traces_available,
            topology_available=topology_available,
            anomalies_count=len(anomaly_events),
            metric_samples_count=len(metric_samples),
            log_entries_count=len(logs_in_window),
            error_logs_count=total_error_logs,
            trace_spans_count=len(full_spans),
            traces_count=total_traces_count,
            incomplete_traces_count=incomplete_traces_count,
            observed_signals=observed_signals,
            missing_signals=missing_signals,
        )

        now_utc = datetime.now(timezone.utc)
        canonical_payload = {
            "project_id": str(project_id),
            "window_start": w_start.isoformat(),
            "window_end": w_end.isoformat(),
            "metrics": [
                (str(m.service_id), m.metric_name, m.sample_count, round(m.mean_value, 4), m.status)
                for m in metric_summaries
            ],
            "logs": [str(lg.log_id) for lg in log_highlights],
            "traces": [(t.trace_id, t.span_id, t.self_time_ms, t.is_origin_error) for t in trace_bottlenecks],
        }
        ev_hash = hashlib.sha256(json.dumps(canonical_payload, sort_keys=True).encode("utf-8")).hexdigest()

        summary = MultiSignalEvidenceSummary(
            correlation_group_id=correlation_group_id,
            project_id=project_id,
            time_window_start=w_start,
            time_window_end=w_end,
            evidence_version="2.0",
            evidence_hash=ev_hash,
            computed_at=now_utc,
            coverage=coverage,
            metric_summaries=metric_summaries,
            log_highlights=log_highlights,
            trace_bottlenecks=trace_bottlenecks,
            timeline=timeline,
            primary_suspected_operation=primary_op,
            affected_downstream_services=affected_downstream,
            contradictory_signals=global_contradictions,
            neutral_signals=global_neutral,
            missing_signals=missing_signals,
            uncertainty_notes=uncertainty_notes,
        )

        return MultiSignalBundle(
            summary=summary,
            service_profiles=profiles,
            has_any_telemetry=(metrics_available or logs_available or traces_available),
        )

    def _analyze_metrics(
        self,
        metric_samples: List[MetricSample],
        baseline_samples: List[MetricSample],
        persisted_baselines: Dict[Tuple[UUID, str], float],
        services_map: Dict[UUID, Service],
        profiles: Dict[UUID, ServiceSignalProfile],
    ) -> List[ServiceMetricEvidence]:
        grouped: Dict[Tuple[UUID, str], List[MetricSample]] = {}
        for m in metric_samples:
            grouped.setdefault((m.service_id, m.metric_name), []).append(m)

        base_grouped: Dict[Tuple[UUID, str], List[float]] = {}
        for bm in baseline_samples:
            base_grouped.setdefault((bm.service_id, bm.metric_name), []).append(float(bm.value))

        summaries: List[ServiceMetricEvidence] = []
        per_svc_scores: Dict[UUID, List[float]] = {}

        for (sid, mname), rows in sorted(grouped.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
            svc = services_map.get(sid)
            if not svc:
                continue
            profile = profiles[sid]
            profile.has_metric_samples = True
            if mname not in profile.referenced_metric_names:
                profile.referenced_metric_names.append(mname)

            vals = [float(r.value) for r in rows]
            sorted_vals = sorted(vals)
            count = len(vals)
            min_v = round(sorted_vals[0], 2)
            max_v = round(sorted_vals[-1], 2)
            mean_v = round(sum(vals) / count, 2)
            p95_v = _percentile(sorted_vals, 95.0) if count >= 5 else None

            base_vals = base_grouped.get((sid, mname), [])
            baseline_mean: Optional[float] = None
            base_count = len(base_vals)
            if base_count >= 3:
                baseline_mean = round(sum(base_vals) / base_count, 2)
            elif (sid, mname) in persisted_baselines:
                baseline_mean = round(persisted_baselines[(sid, mname)], 2)

            dev_pct: Optional[float] = None
            if baseline_mean is not None:
                if baseline_mean > 0.001:
                    dev_pct = round(((mean_v - baseline_mean) / baseline_mean) * 100.0, 2)
                elif mean_v > 0.0:
                    dev_pct = 100.0

            is_anomalous = False
            status = "normal"
            first_breach: Optional[datetime] = None
            sig_score = 0.0

            if count < 2 and baseline_mean is None:
                status = "insufficient_samples"
            elif mname == "latency":
                thresh = max(300.0, (baseline_mean * 1.5) if baseline_mean else 300.0)
                if (dev_pct is not None and dev_pct >= 50.0 and mean_v >= 120.0) or (p95_v and p95_v >= 450.0) or max_v >= 500.0:
                    is_anomalous = True
                    status = "anomalous"
                    breach_rows = [r for r in rows if float(r.value) >= thresh]
                    if breach_rows:
                        first_breach = _to_utc(breach_rows[0].timestamp)
                    dev_ratio = min(1.0, max(0.0, (dev_pct or 100.0) / 400.0))
                    abs_ratio = min(1.0, max_v / 1000.0)
                    sig_score = round(0.45 + 0.35 * dev_ratio + 0.20 * abs_ratio, 4)
            elif mname == "error_rate":
                if (mean_v >= 5.0 or max_v >= 10.0) and (baseline_mean is None or mean_v >= baseline_mean + 3.0):
                    is_anomalous = True
                    status = "anomalous"
                    breach_rows = [r for r in rows if float(r.value) >= 5.0]
                    if breach_rows:
                        first_breach = _to_utc(breach_rows[0].timestamp)
                    sig_score = round(min(1.0, 0.55 + 0.45 * min(1.0, max(mean_v, max_v) / 50.0)), 4)
            elif any(k in mname for k in ("cpu", "memory", "pool", "saturation")):
                if mean_v >= 85.0 or (dev_pct is not None and dev_pct >= 50.0):
                    is_anomalous = True
                    status = "anomalous"
                    first_breach = _to_utc(rows[0].timestamp)
                    sig_score = round(min(1.0, 0.50 + 0.50 * min(1.0, mean_v / 100.0)), 4)
            elif mname == "request_rate" and dev_pct is not None and dev_pct <= -50.0:
                is_anomalous = True
                status = "anomalous"
                first_breach = _to_utc(rows[0].timestamp)
                sig_score = round(min(0.8, 0.35 + abs(dev_pct) / 200.0), 4)

            if is_anomalous:
                profile.has_anomalous_metrics = True
                if dev_pct is not None and abs(dev_pct) > profile.max_metric_deviation_pct:
                    profile.max_metric_deviation_pct = abs(dev_pct)
                if first_breach and (profile.earliest_metric_breach_at is None or first_breach < profile.earliest_metric_breach_at):
                    profile.earliest_metric_breach_at = first_breach
                per_svc_scores.setdefault(sid, []).append(sig_score)
                p95_txt = f", p95={p95_v}" if p95_v is not None else ""
                dev_txt = f" ({dev_pct:+.1f}% vs baseline)" if dev_pct is not None else ""
                profile.supporting_items.append(
                    f"Persisted metric '{mname}': mean={mean_v}{rows[0].metric_unit or ''}{p95_txt}, max={max_v}{dev_txt} across {count} samples."
                )

            summaries.append(
                ServiceMetricEvidence(
                    service_id=sid,
                    service_slug=svc.slug,
                    service_name=svc.name,
                    metric_name=mname,
                    metric_unit=rows[0].metric_unit or "",
                    sample_count=count,
                    baseline_sample_count=base_count,
                    min_value=min_v,
                    max_value=max_v,
                    mean_value=mean_v,
                    p95_value=p95_v,
                    baseline_mean=baseline_mean,
                    deviation_pct=dev_pct,
                    is_anomalous=is_anomalous,
                    status=status,
                    first_breach_at=first_breach,
                )
            )

        for sid, scores in per_svc_scores.items():
            profiles[sid].metric_score = round(max(scores), 4)

        return summaries

    def _analyze_traces(
        self,
        spans: List[TraceSpan],
        services_map: Dict[UUID, Service],
        profiles: Dict[UUID, ServiceSignalProfile],
    ) -> Tuple[List[BottleneckSpanEvidence], int, int, List[str]]:
        if not spans:
            return [], 0, 0, []

        spans_by_trace: Dict[str, List[TraceSpan]] = {}
        for sp in spans:
            spans_by_trace.setdefault(sp.trace_id, []).append(sp)

        all_bottlenecks: List[BottleneckSpanEvidence] = []
        incomplete_traces = 0
        notes: List[str] = []

        svc_anomalous_traces: Dict[UUID, Set[str]] = {}
        svc_bottleneck_traces: Dict[UUID, Set[str]] = {}
        svc_origin_error_traces: Dict[UUID, Set[str]] = {}
        svc_self_shares: Dict[UUID, List[float]] = {}

        anomalous_trace_count = 0

        for trace_id, tr_spans in spans_by_trace.items():
            ordered = sorted(tr_spans, key=lambda s: (_to_utc(s.start_time), str(s.span_id)))
            present_ids: Set[str] = {s.span_id for s in ordered}
            children_by_parent: Dict[Optional[str], List[TraceSpan]] = {}
            missing_parent_found = False

            for s in ordered:
                if s.parent_span_id and s.parent_span_id not in present_ids:
                    missing_parent_found = True
                    p_key = None
                else:
                    p_key = s.parent_span_id
                children_by_parent.setdefault(p_key, []).append(s)

            if missing_parent_found:
                incomplete_traces += 1

            roots = children_by_parent.get(None, []) or [ordered[0]]
            min_start = min(_to_utc(s.start_time) for s in ordered)
            max_end = max(_to_utc(s.end_time) for s in ordered)
            total_dur_ms = max(
                1.0,
                max((max_end - min_start).total_seconds() * 1000.0, max(float(s.duration_ms or 0.0) for s in roots)),
            )

            def _is_err(sp_obj: TraceSpan) -> bool:
                return sp_obj.status == "error" or (sp_obj.http_status_code is not None and sp_obj.http_status_code >= 500)

            has_error = any(_is_err(s) for s in ordered)
            is_slow = total_dur_ms >= 350.0
            if not (has_error or is_slow):
                continue

            anomalous_trace_count += 1
            for s in ordered:
                if s.service_id in profiles:
                    profiles[s.service_id].has_traces = True
                    svc_anomalous_traces.setdefault(s.service_id, set()).add(trace_id)
                    if trace_id not in profiles[s.service_id].referenced_trace_ids and len(profiles[s.service_id].referenced_trace_ids) < 10:
                        profiles[s.service_id].referenced_trace_ids.append(trace_id)

            # Exclusive self-time calculation per span prevents blaming outer caller HTTP wrappers
            self_times: Dict[str, float] = {}
            for s in ordered:
                direct_children = children_by_parent.get(s.span_id, [])
                child_sum = sum(max(0.0, float(c.duration_ms or 0.0)) for c in direct_children)
                self_times[s.span_id] = max(0.0, float(s.duration_ms or 0.0) - child_sum)

            bottleneck_span = max(ordered, key=lambda x: self_times[x.span_id])
            bottleneck_self = self_times[bottleneck_span.span_id]
            bottleneck_share = bottleneck_self / total_dur_ms
            has_real_bottleneck = (bottleneck_share >= 0.35) or (bottleneck_self >= 250.0)

            # Origin error span: failed span with ZERO failing descendant spans (leaf fault origin)
            failed_spans = [s for s in ordered if _is_err(s)]
            origin_error_span_ids: Set[str] = set()
            if failed_spans:
                def _has_failed_descendant(sp_id: str) -> bool:
                    for ch in children_by_parent.get(sp_id, []):
                        if _is_err(ch) or _has_failed_descendant(ch.span_id):
                            return True
                    return False

                leaf_failed = [s for s in failed_spans if not _has_failed_descendant(s.span_id)]
                if leaf_failed:
                    chosen = max(leaf_failed, key=lambda s: (_to_utc(s.start_time), self_times[s.span_id]))
                    origin_error_span_ids.add(chosen.span_id)

            # Collect notable spans for this trace
            selected_spans: Dict[str, TraceSpan] = {}
            if has_real_bottleneck:
                selected_spans[bottleneck_span.span_id] = bottleneck_span
            for oid in origin_error_span_ids:
                for s in ordered:
                    if s.span_id == oid:
                        selected_spans[s.span_id] = s

            for sp in selected_spans.values():
                sid = sp.service_id
                s_self = round(self_times[sp.span_id], 2)
                s_share = round(min(1.0, self_times[sp.span_id] / total_dur_ms), 4)
                is_bn = has_real_bottleneck and sp.span_id == bottleneck_span.span_id
                is_orig = sp.span_id in origin_error_span_ids

                if sid in profiles:
                    prof = profiles[sid]
                    if is_bn:
                        svc_bottleneck_traces.setdefault(sid, set()).add(trace_id)
                        svc_self_shares.setdefault(sid, []).append(s_share)
                        if s_self > prof.max_span_self_time_ms:
                            prof.max_span_self_time_ms = s_self
                            prof.suspected_operation = sp.operation_name
                    if is_orig:
                        svc_origin_error_traces.setdefault(sid, set()).add(trace_id)
                        if prof.suspected_operation is None:
                            prof.suspected_operation = sp.operation_name

                    sp_t = _to_utc(sp.start_time)
                    if prof.earliest_fault_span_at is None or sp_t < prof.earliest_fault_span_at:
                        prof.earliest_fault_span_at = sp_t
                    if sp.span_id not in prof.referenced_span_ids and len(prof.referenced_span_ids) < 15:
                        prof.referenced_span_ids.append(sp.span_id)

                svc = services_map.get(sid)
                all_bottlenecks.append(
                    BottleneckSpanEvidence(
                        trace_id=trace_id,
                        span_id=sp.span_id,
                        parent_span_id=sp.parent_span_id,
                        service_id=sid,
                        service_slug=svc.slug if svc else "unknown",
                        service_name=svc.name if svc else "Unknown Service",
                        operation_name=sp.operation_name,
                        span_kind=sp.span_kind,
                        duration_ms=round(float(sp.duration_ms or 0.0), 2),
                        self_time_ms=s_self,
                        self_time_share=s_share,
                        status=sp.status,
                        http_status_code=sp.http_status_code,
                        error_message=redact_secrets(sp.error_message),
                        start_time=_to_utc(sp.start_time),
                        is_origin_error=is_orig,
                        is_bottleneck=is_bn,
                        has_missing_parent=bool(sp.parent_span_id and sp.parent_span_id not in present_ids),
                    )
                )

        # Normalize trace bottleneck score per service
        total_anomalous = max(1, anomalous_trace_count)
        for sid, prof in profiles.items():
            if not prof.has_traces:
                continue
            owned = svc_bottleneck_traces.get(sid, set()) | svc_origin_error_traces.get(sid, set())
            prof.participating_anomalous_traces = len(svc_anomalous_traces.get(sid, set()))
            prof.bottleneck_traces_owned = len(svc_bottleneck_traces.get(sid, set()))
            prof.origin_error_traces_owned = len(svc_origin_error_traces.get(sid, set()))
            shares = svc_self_shares.get(sid, [])
            avg_share = (sum(shares) / len(shares)) if shares else 0.0
            prof.avg_bottleneck_self_time_share = round(avg_share, 4)

            if owned:
                own_fraction = len(owned) / total_anomalous
                prof.trace_score = round(min(1.0, 0.65 * own_fraction + 0.35 * max(avg_share, 0.65 if prof.origin_error_traces_owned else 0.0)), 4)
                prof.supporting_items.append(
                    f"Trace span analysis: owns {len(owned)}/{anomalous_trace_count} anomalous trace bottlenecks/origin errors "
                    f"(avg self-time share {avg_share * 100:.1f}%, operation '{prof.suspected_operation or 'unknown'}')."
                )
            elif prof.participating_anomalous_traces > 0:
                prof.trace_score = 0.05
                prof.supporting_items.append(
                    f"Participated in {prof.participating_anomalous_traces} anomalous traces primarily as waiting caller/wrapper span."
                )

        if incomplete_traces > 0:
            notes.append(
                f"{incomplete_traces} trace(s) had missing parent spans (partial trace propagation)."
            )

        all_bottlenecks.sort(
            key=lambda b: (b.is_origin_error, b.is_bottleneck, b.self_time_ms),
            reverse=True,
        )
        return all_bottlenecks[: self.MAX_BOTTLENECK_SPANS], len(spans_by_trace), incomplete_traces, notes

    def _analyze_logs(
        self,
        logs: List[ApplicationLog],
        services_map: Dict[UUID, Service],
        profiles: Dict[UUID, ServiceSignalProfile],
    ) -> Tuple[List[CorrelatedLogHighlight], int]:
        if not logs:
            return [], 0

        dedup_err_keys: Dict[UUID, Set[str]] = {}
        dedup_warn_keys: Dict[UUID, Set[str]] = {}
        origin_err_keys: Dict[UUID, Set[str]] = {}
        total_err_logs = 0
        highlights: List[CorrelatedLogHighlight] = []

        for lg in logs:
            sid = lg.service_id
            if sid not in profiles:
                continue
            prof = profiles[sid]
            prof.has_logs = True
            prof.total_logs_count += 1

            lvl = (lg.level or "INFO").upper()
            dedup_key = lg.trace_id or lg.source_event_id or str(lg.id)
            pattern = _classify_log_pattern(lg.message or "", lg.exception_type, lvl)

            if lvl in ("ERROR", "CRITICAL"):
                total_err_logs += 1
                prof.error_logs_count += 1
                dedup_err_keys.setdefault(sid, set()).add(dedup_key)
                if not _PROPAGATION_PATTERN.search(lg.message or ""):
                    origin_err_keys.setdefault(sid, set()).add(dedup_key)
                    prof.origin_error_log_count += 1
                lg_t = _to_utc(lg.timestamp)
                if prof.earliest_error_log_at is None or lg_t < prof.earliest_error_log_at:
                    prof.earliest_error_log_at = lg_t
            elif lvl == "WARNING":
                dedup_warn_keys.setdefault(sid, set()).add(dedup_key)

            if lvl in ("CRITICAL", "ERROR", "WARNING") and len(highlights) < self.MAX_HIGHLIGHT_LOGS:
                svc = services_map.get(sid)
                highlights.append(
                    CorrelatedLogHighlight(
                        log_id=lg.id,
                        service_id=sid,
                        service_slug=svc.slug if svc else "unknown",
                        service_name=svc.name if svc else "Unknown Service",
                        timestamp=_to_utc(lg.timestamp),
                        level=lvl,
                        message=redact_secrets(lg.message) or "",
                        trace_id=lg.trace_id,
                        request_id=lg.request_id,
                        exception_type=lg.exception_type,
                        pattern_category=pattern,
                    )
                )
                if str(lg.id) not in prof.referenced_log_ids:
                    prof.referenced_log_ids.append(str(lg.id))

        max_distinct_err = max((len(v) for v in dedup_err_keys.values()), default=0)
        for sid, prof in profiles.items():
            if not prof.has_logs:
                continue
            err_k = len(dedup_err_keys.get(sid, set()))
            warn_k = len(dedup_warn_keys.get(sid, set()))
            orig_k = len(origin_err_keys.get(sid, set()))
            prof.distinct_error_keys = err_k
            prof.distinct_warning_keys = warn_k

            if err_k > 0 and max_distinct_err > 0:
                err_ratio = err_k / max_distinct_err
                origin_bonus = 0.25 if orig_k > 0 else 0.0
                prof.log_score = round(min(1.0, 0.75 * err_ratio + origin_bonus), 4)
                prof.supporting_items.append(
                    f"Structured logs: {err_k} distinct failing request/trace error(s) ({prof.error_logs_count} total ERROR/CRITICAL rows)."
                )
            elif warn_k > 0:
                prof.log_score = round(min(0.45, 0.20 + 0.05 * warn_k), 4)
                prof.supporting_items.append(
                    f"Structured logs: {warn_k} distinct latency/retry WARNING signal(s)."
                )

        # Prioritize CRITICAL/ERROR highlights first while preserving chronological order inside severity
        sev_prio = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2}
        highlights.sort(key=lambda h: (sev_prio.get(h.level, 3), h.timestamp))
        return highlights, total_err_logs

    def _evaluate_cross_signal_alignment(
        self,
        services_map: Dict[UUID, Service],
        profiles: Dict[UUID, ServiceSignalProfile],
        anomaly_events: List[AnomalyEvent],
        metrics_available: bool,
        logs_available: bool,
        traces_available: bool,
        global_contradictions: List[str],
        global_neutral: List[str],
    ) -> None:
        anom_services = {e.service_id for e in anomaly_events}
        any_trace_owner_elsewhere = any(
            (p.bottleneck_traces_owned > 0 or p.origin_error_traces_owned > 0) for p in profiles.values()
        )
        any_error_logs_elsewhere = any(p.error_logs_count > 0 for p in profiles.values())

        for sid, prof in profiles.items():
            svc_name = services_map[sid].name if sid in services_map else str(sid)
            if sid in anom_services:
                # Contradiction 1: Anomalous service has persisted traces with zero bottleneck/origin ownership while another service owns trace fault
                if (
                    traces_available
                    and prof.has_traces
                    and prof.bottleneck_traces_owned == 0
                    and prof.origin_error_traces_owned == 0
                    and any_trace_owner_elsewhere
                ):
                    msg = (
                        f"Trace contradiction on {svc_name}: anomalous event/metric present, but persisted trace trees attribute bottleneck/origin error to downstream/other service spans."
                    )
                    prof.contradictory_items.append(msg)
                    global_contradictions.append(msg)

                # Contradiction 2: Severe anomaly claimed, yet substantial logs exist with zero ERROR/CRITICAL entries while another service logged errors
                if (
                    logs_available
                    and prof.has_logs
                    and prof.total_logs_count >= 4
                    and prof.error_logs_count == 0
                    and any_error_logs_elsewhere
                ):
                    msg = (
                        f"Log contradiction on {svc_name}: 0 ERROR/CRITICAL logs across {prof.total_logs_count} entries despite anomaly event, while another service logged active errors."
                    )
                    prof.contradictory_items.append(msg)
                    global_contradictions.append(msg)
            else:
                if metrics_available and prof.has_metric_samples and not prof.has_anomalous_metrics:
                    msg = f"{svc_name}: metrics remained within baseline limits (neutral)."
                    prof.neutral_items.append(msg)
                    global_neutral.append(msg)

    def _build_timeline(
        self,
        anomaly_events: List[AnomalyEvent],
        metric_summaries: List[ServiceMetricEvidence],
        log_highlights: List[CorrelatedLogHighlight],
        trace_bottlenecks: List[BottleneckSpanEvidence],
        services_map: Dict[UUID, Service],
    ) -> List[MultiSignalTimelineEntry]:
        entries: List[MultiSignalTimelineEntry] = []

        for ev in anomaly_events:
            svc = services_map.get(ev.service_id)
            entries.append(
                MultiSignalTimelineEntry(
                    timestamp=_to_utc(ev.occurred_at),
                    signal_type="anomaly",
                    service_id=ev.service_id,
                    service_slug=svc.slug if svc else "unknown",
                    service_name=svc.name if svc else "Unknown Service",
                    severity=ev.severity.upper(),
                    title=f"Anomaly detected on '{ev.metric_name}'",
                    detail=f"Observed {ev.observed_value:.2f} (deviation: {ev.deviation_pct:+.1f}%)" if ev.deviation_pct is not None else f"Observed {ev.observed_value:.2f}",
                    reference_id=str(ev.id),
                )
            )

        for ms in metric_summaries:
            if ms.is_anomalous and ms.first_breach_at:
                entries.append(
                    MultiSignalTimelineEntry(
                        timestamp=ms.first_breach_at,
                        signal_type="metric",
                        service_id=ms.service_id,
                        service_slug=ms.service_slug,
                        service_name=ms.service_name,
                        severity="HIGH",
                        title=f"Metric threshold breach: {ms.metric_name}",
                        detail=f"Mean={ms.mean_value}{ms.metric_unit}, Max={ms.max_value}{ms.metric_unit} across {ms.sample_count} samples",
                        reference_id=ms.metric_name,
                    )
                )

        for lg in log_highlights[:10]:
            entries.append(
                MultiSignalTimelineEntry(
                    timestamp=lg.timestamp,
                    signal_type="log",
                    service_id=lg.service_id,
                    service_slug=lg.service_slug,
                    service_name=lg.service_name,
                    severity=lg.level,
                    title=f"{lg.level} log ({lg.pattern_category or 'application'})",
                    detail=lg.message[:220],
                    reference_id=str(lg.log_id),
                )
            )

        for tb in trace_bottlenecks[:10]:
            entries.append(
                MultiSignalTimelineEntry(
                    timestamp=tb.start_time,
                    signal_type="trace",
                    service_id=tb.service_id,
                    service_slug=tb.service_slug,
                    service_name=tb.service_name,
                    severity="CRITICAL" if tb.is_origin_error else "HIGH",
                    title=f"{'Origin error' if tb.is_origin_error else 'Bottleneck'} span: {tb.operation_name}",
                    detail=f"duration={tb.duration_ms:.1f}ms, self_time={tb.self_time_ms:.1f}ms ({tb.self_time_share * 100:.0f}%)",
                    reference_id=tb.trace_id,
                )
            )

        entries.sort(key=lambda x: (x.timestamp, x.signal_type, x.service_slug))
        return entries[: self.MAX_TIMELINE_ITEMS]
