"""Distributed request tracing ingestion, parent-child tree reconstruction, and waterfall query service."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import UUID, uuid4
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.service import Service
from app.models.telemetry import TraceSpan
from app.repositories.project_repository import ProjectRepository
from app.repositories.service_repository import ServiceRepository
from app.repositories.telemetry_repository import TraceSpanRepository
from app.schemas.telemetry import (
    SpanBatchIngestRequest,
    SpanBatchIngestResponse,
    TraceListResponse,
    TraceSummaryResponse,
    WaterfallSpanResponse,
)
from app.services.anomaly.service import ServiceNotFoundError
from app.services.telemetry.metrics_service import TelemetryProjectNotFoundError
from app.services.telemetry.redaction import redact_secrets, sanitize_attributes


def _to_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _format_trace_status_label(status_code: int, has_error: bool) -> str:
    if status_code == 504:
        return "504 TIMEOUT"
    if status_code == 502:
        return "502 BAD GATEWAY"
    if status_code >= 500 or has_error:
        return f"{status_code} ERROR" if status_code >= 400 else "500 ERROR"
    return f"{status_code} OK" if status_code > 0 else "200 OK"


class TracesService:
    def __init__(self, db: Session):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.service_repo = ServiceRepository(db)
        self.span_repo = TraceSpanRepository(db)

    def ingest_batch(self, request: SpanBatchIngestRequest) -> SpanBatchIngestResponse:
        project = self.project_repo.get_by_id(request.project_id)
        if not project:
            raise TelemetryProjectNotFoundError(f"Project '{request.project_id}' was not found.")

        accepted_count = 0
        duplicate_count = 0
        span_ids: List[UUID] = []
        service_cache: Dict[str, Service] = {}

        for item in request.spans:
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

            existing = self.span_repo.get_by_trace_and_span(
                project_id=request.project_id,
                trace_id=item.trace_id,
                span_id=item.span_id,
            )
            if existing:
                duplicate_count += 1
                continue

            scrubbed_err = redact_secrets(item.error_message) if item.error_message else None
            scrubbed_attrs = sanitize_attributes(item.attributes)

            span_row = TraceSpan(
                id=uuid4(),
                project_id=request.project_id,
                service_id=svc.id,
                trace_id=item.trace_id,
                span_id=item.span_id,
                parent_span_id=item.parent_span_id,
                operation_name=item.operation_name,
                span_kind=item.span_kind.value,
                start_time=item.start_time,
                end_time=item.end_time,
                duration_ms=float(item.duration_ms or 0.0),
                status=item.status.value,
                http_status_code=item.http_status_code,
                error_message=scrubbed_err[:2048] if scrubbed_err else None,
                request_id=item.request_id,
                attributes_json=scrubbed_attrs,
            )

            try:
                with self.db.begin_nested():
                    self.span_repo.create(span_row, commit=False)
                self.db.commit()
                self.db.refresh(span_row)
                accepted_count += 1
                span_ids.append(span_row.id)
            except IntegrityError:
                duplicate_count += 1
                continue

        return SpanBatchIngestResponse(
            accepted_count=accepted_count,
            duplicate_count=duplicate_count,
            span_ids=span_ids,
        )

    def _build_trace_summary(
        self,
        trace_id: str,
        spans: List[TraceSpan],
        svc_map: Dict[UUID, Service],
        include_waterfall: bool = False,
    ) -> TraceSummaryResponse:
        # Sort deterministically by start_time
        ordered = sorted(spans, key=lambda s: (_to_utc(s.start_time), s.span_id))

        # Root span: parent_span_id is None, or earliest span if orphaned
        root = next((s for s in ordered if s.parent_span_id is None), ordered[0])
        root_svc = svc_map.get(root.service_id)

        min_start = min(_to_utc(s.start_time) for s in ordered)
        max_end = max(_to_utc(s.end_time) for s in ordered)
        total_duration_ms = max(
            round((max_end - min_start).total_seconds() * 1000.0, 2),
            round(root.duration_ms, 2),
        )

        has_error = any(s.status == "error" for s in ordered)
        status_code = root.http_status_code or (500 if has_error else 200)
        anomalous = has_error or total_duration_ms >= 500.0

        waterfall: Optional[List[WaterfallSpanResponse]] = None
        if include_waterfall:
            children_by_parent: Dict[Optional[str], List[TraceSpan]] = {}
            present_span_ids: Set[str] = {s.span_id for s in ordered}
            for s in ordered:
                # Attach spans whose parent isn't in trace cleanly under None (orphaned top-level)
                p_key = s.parent_span_id if s.parent_span_id in present_span_ids else None
                children_by_parent.setdefault(p_key, []).append(s)

            # Tree traversal for proper waterfall ordering & depth
            dfs_ordered: List[tuple[TraceSpan, int]] = []
            visited: Set[str] = set()

            def _visit(parent_key: Optional[str], depth: int) -> None:
                for child in sorted(children_by_parent.get(parent_key, []), key=lambda x: _to_utc(x.start_time)):
                    if child.span_id in visited:
                        continue
                    visited.add(child.span_id)
                    dfs_ordered.append((child, depth))
                    _visit(child.span_id, depth + 1)

            _visit(None, 0)
            # Append any remaining cyclic/unvisited spans safely
            for s in ordered:
                if s.span_id not in visited:
                    dfs_ordered.append((s, 0))

            # Identify bottleneck span using exclusive self-time (span duration minus direct children)
            # so slow leaf work (e.g. payment.gateway_charge) wins over outer HTTP client/server wrappers.
            denom_ms = max(total_duration_ms, 0.001)

            def _self_time_ms(span_obj: TraceSpan) -> float:
                direct_children = children_by_parent.get(span_obj.span_id, [])
                child_sum = sum(max(0.0, float(c.duration_ms)) for c in direct_children)
                return max(0.0, float(span_obj.duration_ms) - child_sum)

            slowest_span = max(ordered, key=_self_time_ms)
            slowest_self_ms = _self_time_ms(slowest_span)
            bottleneck_id = (
                slowest_span.span_id
                if (slowest_self_ms / denom_ms >= 0.35 or slowest_self_ms >= 300.0)
                else None
            )

            waterfall = []
            for s, depth in dfs_ordered:
                svc = svc_map.get(s.service_id)
                offset_ms = (_to_utc(s.start_time) - min_start).total_seconds() * 1000.0
                offset_pct = round(max(0.0, min(100.0, (offset_ms / denom_ms) * 100.0)), 2)
                width_pct = round(max(1.0, min(100.0 - offset_pct, (s.duration_ms / denom_ms) * 100.0)), 2)

                exc_obj = None
                if s.status == "error" and s.error_message:
                    exc_obj = {
                        "type": "SpanError",
                        "message": s.error_message,
                        "stackTrace": [],
                    }

                waterfall.append(
                    WaterfallSpanResponse(
                        id=s.span_id,
                        span_id=s.span_id,
                        parent_span_id=s.parent_span_id,
                        name=s.operation_name,
                        service=svc.name if svc else "Unknown Service",
                        service_slug=svc.slug if svc else "unknown",
                        operation=s.operation_name,
                        span_kind=s.span_kind,
                        start_time=_to_utc(s.start_time),
                        end_time=_to_utc(s.end_time),
                        durationMs=round(s.duration_ms, 2),
                        offsetPercent=offset_pct,
                        widthPercent=width_pct,
                        status=s.status,
                        httpStatus=s.http_status_code,
                        isBottleneck=(s.span_id == bottleneck_id),
                        depth=depth,
                        hasChildren=bool(children_by_parent.get(s.span_id)),
                        request_id=s.request_id,
                        attributes=s.attributes_json or {},
                        exception=exc_obj,
                    )
                )

        return TraceSummaryResponse(
            id=trace_id,
            project_id=root.project_id,
            rootService=root_svc.name if root_svc else "Unknown Service",
            rootServiceSlug=root_svc.slug if root_svc else "unknown",
            rootEndpoint=root.operation_name,
            durationMs=total_duration_ms,
            spansCount=len(ordered),
            status=_format_trace_status_label(status_code, has_error),
            statusCode=status_code,
            timestamp=min_start,
            anomalous=anomalous,
            spans=waterfall,
        )

    def list_traces(
        self,
        project_id: Optional[UUID] = None,
        service_identifier: Optional[str] = None,
        status: Optional[str] = None,
        min_duration_ms: Optional[float] = None,
        trace_id_prefix: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> TraceListResponse:
        resolved_service_id: Optional[UUID] = None
        if service_identifier:
            try:
                resolved_service_id = UUID(service_identifier)
            except ValueError:
                q = self.db.query(Service).filter(
                    (Service.slug == service_identifier)
                    | (Service.identifier == service_identifier)
                    | (Service.name == service_identifier)
                )
                if project_id:
                    q = q.filter(Service.project_id == project_id)
                svc = q.first()
                if not svc:
                    return TraceListResponse(items=[], total=0, page=1, page_size=limit, total_pages=1)
                resolved_service_id = svc.id

        trace_ids, total = self.span_repo.list_trace_ids(
            project_id=project_id,
            service_id=resolved_service_id,
            status=status,
            min_duration_ms=min_duration_ms,
            trace_id_prefix=trace_id_prefix,
            start_time=start_time,
            end_time=end_time,
            skip=skip,
            limit=limit,
        )

        if not trace_ids:
            return TraceListResponse(items=[], total=0, page=(skip // limit) + 1, page_size=limit, total_pages=1)

        q_spans = self.db.query(TraceSpan).filter(TraceSpan.trace_id.in_(trace_ids))
        if project_id:
            q_spans = q_spans.filter(TraceSpan.project_id == project_id)
        all_spans = q_spans.all()

        svc_ids = {s.service_id for s in all_spans}
        svc_map = (
            {s.id: s for s in self.db.query(Service).filter(Service.id.in_(svc_ids)).all()}
            if svc_ids
            else {}
        )

        spans_by_trace: Dict[str, List[TraceSpan]] = {}
        for s in all_spans:
            spans_by_trace.setdefault(s.trace_id, []).append(s)

        summaries = [
            self._build_trace_summary(tid, spans_by_trace[tid], svc_map, include_waterfall=False)
            for tid in trace_ids
            if tid in spans_by_trace
        ]

        page = (skip // limit) + 1
        total_pages = max(1, (total + limit - 1) // limit)
        return TraceListResponse(
            items=summaries,
            total=total,
            page=page,
            page_size=limit,
            total_pages=total_pages,
        )

    def get_trace_detail(
        self,
        trace_id: str,
        project_id: Optional[UUID] = None,
    ) -> Optional[TraceSummaryResponse]:
        spans = self.span_repo.get_spans_for_trace(trace_id=trace_id, project_id=project_id)
        if not spans:
            return None

        svc_ids = {s.service_id for s in spans}
        svc_map = (
            {s.id: s for s in self.db.query(Service).filter(Service.id.in_(svc_ids)).all()}
            if svc_ids
            else {}
        )
        return self._build_trace_summary(trace_id, spans, svc_map, include_waterfall=True)
