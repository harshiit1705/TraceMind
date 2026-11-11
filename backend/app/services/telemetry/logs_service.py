"""Structured application logging ingestion, redaction, filtering, and incident-log retrieval service."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.correlation import CorrelationGroup
from app.models.incident import Incident
from app.models.service import Service
from app.models.telemetry import ApplicationLog
from app.repositories.incident_repository import IncidentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.service_repository import ServiceRepository
from app.repositories.telemetry_repository import ApplicationLogRepository
from app.schemas.telemetry import (
    ApplicationLogResponse,
    LogBatchIngestRequest,
    LogBatchIngestResponse,
)
from app.services.anomaly.service import ServiceNotFoundError
from app.services.incident_service import IncidentNotFoundError
from app.services.telemetry.metrics_service import TelemetryProjectNotFoundError
from app.services.telemetry.redaction import redact_secrets, sanitize_attributes


class LogsService:
    def __init__(self, db: Session):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.service_repo = ServiceRepository(db)
        self.log_repo = ApplicationLogRepository(db)
        self.incident_repo = IncidentRepository(db)

    def ingest_batch(self, request: LogBatchIngestRequest) -> LogBatchIngestResponse:
        project = self.project_repo.get_by_id(request.project_id)
        if not project:
            raise TelemetryProjectNotFoundError(f"Project '{request.project_id}' was not found.")

        accepted_count = 0
        duplicate_count = 0
        log_ids: List[UUID] = []
        service_cache: Dict[str, Service] = {}

        for item in request.logs:
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

            if item.source_event_id:
                existing = self.log_repo.get_by_source_event_id(
                    project_id=request.project_id,
                    service_id=svc.id,
                    source_event_id=item.source_event_id,
                )
                if existing:
                    duplicate_count += 1
                    continue

            ts = item.timestamp or datetime.now(timezone.utc)
            scrubbed_message = redact_secrets(item.message) or ""
            scrubbed_exc_msg = redact_secrets(item.exception_message) if item.exception_message else None
            scrubbed_attrs = sanitize_attributes(item.attributes)

            log_row = ApplicationLog(
                id=uuid4(),
                project_id=request.project_id,
                service_id=svc.id,
                timestamp=ts,
                level=item.level,
                message=scrubbed_message[:8192],
                request_id=item.request_id,
                trace_id=item.trace_id,
                span_id=item.span_id,
                source_event_id=item.source_event_id,
                attributes_json=scrubbed_attrs,
                exception_type=item.exception_type,
                exception_message=scrubbed_exc_msg[:4096] if scrubbed_exc_msg else None,
            )

            try:
                with self.db.begin_nested():
                    self.log_repo.create(log_row, commit=False)
                self.db.commit()
                self.db.refresh(log_row)
                accepted_count += 1
                log_ids.append(log_row.id)
            except IntegrityError:
                duplicate_count += 1
                continue

        return LogBatchIngestResponse(
            accepted_count=accepted_count,
            duplicate_count=duplicate_count,
            log_ids=log_ids,
        )

    def _enrich_logs(self, rows: List[ApplicationLog]) -> List[ApplicationLogResponse]:
        if not rows:
            return []
        svc_ids = {r.service_id for r in rows}
        svc_map = {s.id: s for s in self.db.query(Service).filter(Service.id.in_(svc_ids)).all()}
        out: List[ApplicationLogResponse] = []
        for r in rows:
            svc = svc_map.get(r.service_id)
            dto = ApplicationLogResponse.model_validate(r)
            dto.service_slug = svc.slug if svc else None
            dto.service_name = svc.name if svc else None
            out.append(dto)
        return out

    def query_logs(
        self,
        project_id: Optional[UUID] = None,
        service_identifier: Optional[str] = None,
        level: Optional[str] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        search: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[ApplicationLogResponse], int]:
        service_ids: Optional[List[UUID]] = None
        if service_identifier:
            try:
                service_ids = [UUID(service_identifier)]
            except ValueError:
                q = self.db.query(Service).filter(
                    (Service.slug == service_identifier)
                    | (Service.identifier == service_identifier)
                    | (Service.name == service_identifier)
                )
                if project_id:
                    q = q.filter(Service.project_id == project_id)
                matches = q.all()
                if not matches:
                    return [], 0
                service_ids = [s.id for s in matches]

        rows, total = self.log_repo.query(
            project_id=project_id,
            service_ids=service_ids,
            level=level,
            request_id=request_id,
            trace_id=trace_id,
            search=search,
            start_time=start_time,
            end_time=end_time,
            skip=skip,
            limit=limit,
        )
        return self._enrich_logs(rows), total

    def get_logs_for_incident(
        self,
        incident_identifier: str,
        level: Optional[str] = None,
        trace_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[ApplicationLogResponse], int]:
        incident: Optional[Incident] = None
        try:
            inc_uuid = UUID(incident_identifier)
            incident = self.incident_repo.get_by_id(inc_uuid)
        except ValueError:
            pass
        if not incident:
            incident = self.incident_repo.get_by_number(incident_identifier)
        if not incident:
            raise IncidentNotFoundError(f"Incident '{incident_identifier}' was not found.")

        service_ids: List[UUID] = []
        start_t: datetime
        end_t: datetime

        if incident.correlation_group_id:
            group = (
                self.db.query(CorrelationGroup)
                .filter(CorrelationGroup.id == incident.correlation_group_id)
                .first()
            )
            if group:
                win_start = group.time_window_start
                win_end = group.time_window_end
                if win_start.tzinfo is None:
                    win_start = win_start.replace(tzinfo=timezone.utc)
                if win_end.tzinfo is None:
                    win_end = win_end.replace(tzinfo=timezone.utc)
                start_t = win_start - timedelta(minutes=5)
                end_t = win_end + timedelta(minutes=5)
                service_ids = list({
                    assoc.anomaly_event.service_id
                    for assoc in group.event_associations
                    if assoc.anomaly_event
                })
            else:
                inc_start = incident.started_at if incident.started_at.tzinfo else incident.started_at.replace(tzinfo=timezone.utc)
                start_t = inc_start - timedelta(minutes=5)
                end_t = datetime.now(timezone.utc)
        else:
            inc_start = incident.started_at if incident.started_at.tzinfo else incident.started_at.replace(tzinfo=timezone.utc)
            inc_end = incident.resolved_at or (inc_start + timedelta(minutes=30))
            if inc_end.tzinfo is None:
                inc_end = inc_end.replace(tzinfo=timezone.utc)
            start_t = inc_start - timedelta(minutes=5)
            end_t = inc_end + timedelta(minutes=5)

            if incident.affected_services:
                svcs = (
                    self.db.query(Service)
                    .filter(
                        Service.project_id == incident.project_id,
                        (Service.name.in_(incident.affected_services)) | (Service.slug.in_(incident.affected_services)),
                    )
                    .all()
                )
                service_ids = [s.id for s in svcs]

        rows, total = self.log_repo.query(
            project_id=incident.project_id,
            service_ids=service_ids or None,
            level=level,
            trace_id=trace_id,
            start_time=start_t,
            end_time=end_t,
            skip=skip,
            limit=limit,
        )
        return self._enrich_logs(rows), total

