"""Repositories for persistent MetricSample, ApplicationLog, and TraceSpan records."""

from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.telemetry import ApplicationLog, MetricSample, TraceSpan


class MetricSampleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_source_event_id(
        self,
        project_id: UUID,
        service_id: UUID,
        metric_name: str,
        source_event_id: str,
    ) -> Optional[MetricSample]:
        return (
            self.db.query(MetricSample)
            .filter(
                MetricSample.project_id == project_id,
                MetricSample.service_id == service_id,
                MetricSample.metric_name == metric_name,
                MetricSample.source_event_id == source_event_id,
            )
            .first()
        )

    def create(self, sample: MetricSample, commit: bool = False) -> MetricSample:
        self.db.add(sample)
        if commit:
            self.db.commit()
            self.db.refresh(sample)
        else:
            self.db.flush()
        return sample

    def query(
        self,
        project_id: Optional[UUID] = None,
        service_id: Optional[UUID] = None,
        metric_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        trace_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[MetricSample], int]:
        q = self.db.query(MetricSample)
        if project_id:
            q = q.filter(MetricSample.project_id == project_id)
        if service_id:
            q = q.filter(MetricSample.service_id == service_id)
        if metric_name:
            q = q.filter(MetricSample.metric_name == metric_name.strip().lower())
        if endpoint:
            q = q.filter(MetricSample.endpoint == endpoint)
        if trace_id:
            q = q.filter(MetricSample.trace_id == trace_id)
        if start_time:
            q = q.filter(MetricSample.timestamp >= start_time)
        if end_time:
            q = q.filter(MetricSample.timestamp <= end_time)

        total = q.count()
        items = q.order_by(MetricSample.timestamp.desc()).offset(skip).limit(limit).all()
        return items, total

    def get_window_samples(
        self,
        project_id: UUID,
        start_time: datetime,
        end_time: datetime,
        max_rows: int = 5000,
    ) -> List[MetricSample]:
        return (
            self.db.query(MetricSample)
            .filter(
                MetricSample.project_id == project_id,
                MetricSample.timestamp >= start_time,
                MetricSample.timestamp <= end_time,
            )
            .order_by(MetricSample.timestamp.asc())
            .limit(max_rows)
            .all()
        )


class ApplicationLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_source_event_id(
        self,
        project_id: UUID,
        service_id: UUID,
        source_event_id: str,
    ) -> Optional[ApplicationLog]:
        return (
            self.db.query(ApplicationLog)
            .filter(
                ApplicationLog.project_id == project_id,
                ApplicationLog.service_id == service_id,
                ApplicationLog.source_event_id == source_event_id,
            )
            .first()
        )

    def create(self, log: ApplicationLog, commit: bool = False) -> ApplicationLog:
        self.db.add(log)
        if commit:
            self.db.commit()
            self.db.refresh(log)
        else:
            self.db.flush()
        return log

    def query(
        self,
        project_id: Optional[UUID] = None,
        service_ids: Optional[List[UUID]] = None,
        level: Optional[str] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        search: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[ApplicationLog], int]:
        q = self.db.query(ApplicationLog)
        if project_id:
            q = q.filter(ApplicationLog.project_id == project_id)
        if service_ids:
            q = q.filter(ApplicationLog.service_id.in_(service_ids))
        if level:
            q = q.filter(ApplicationLog.level == level.strip().upper())
        if request_id:
            q = q.filter(ApplicationLog.request_id == request_id)
        if trace_id:
            q = q.filter(ApplicationLog.trace_id == trace_id)
        if search:
            like_term = f"%{search.strip()}%"
            q = q.filter(
                (ApplicationLog.message.ilike(like_term))
                | (ApplicationLog.exception_message.ilike(like_term))
                | (ApplicationLog.trace_id.ilike(like_term))
                | (ApplicationLog.request_id.ilike(like_term))
            )
        if start_time:
            q = q.filter(ApplicationLog.timestamp >= start_time)
        if end_time:
            q = q.filter(ApplicationLog.timestamp <= end_time)

        total = q.count()
        items = q.order_by(ApplicationLog.timestamp.desc()).offset(skip).limit(limit).all()
        return items, total


class TraceSpanRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_trace_and_span(
        self,
        project_id: UUID,
        trace_id: str,
        span_id: str,
    ) -> Optional[TraceSpan]:
        return (
            self.db.query(TraceSpan)
            .filter(
                TraceSpan.project_id == project_id,
                TraceSpan.trace_id == trace_id,
                TraceSpan.span_id == span_id,
            )
            .first()
        )

    def create(self, span: TraceSpan, commit: bool = False) -> TraceSpan:
        self.db.add(span)
        if commit:
            self.db.commit()
            self.db.refresh(span)
        else:
            self.db.flush()
        return span

    def get_spans_for_trace(
        self,
        trace_id: str,
        project_id: Optional[UUID] = None,
    ) -> List[TraceSpan]:
        q = self.db.query(TraceSpan).filter(TraceSpan.trace_id == trace_id)
        if project_id:
            q = q.filter(TraceSpan.project_id == project_id)
        return q.order_by(TraceSpan.start_time.asc()).all()

    def list_trace_ids(
        self,
        project_id: Optional[UUID] = None,
        service_id: Optional[UUID] = None,
        status: Optional[str] = None,
        min_duration_ms: Optional[float] = None,
        trace_id_prefix: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[str], int]:
        """List distinct trace_ids matching filters, ordered by most recent span start_time."""
        q = self.db.query(
            TraceSpan.trace_id,
            func.max(TraceSpan.start_time).label("latest_start"),
        )
        if project_id:
            q = q.filter(TraceSpan.project_id == project_id)
        if service_id:
            q = q.filter(TraceSpan.service_id == service_id)
        if status:
            q = q.filter(TraceSpan.status == status.strip().lower())
        if min_duration_ms is not None:
            q = q.filter(TraceSpan.duration_ms >= min_duration_ms)
        if trace_id_prefix:
            q = q.filter(TraceSpan.trace_id.ilike(f"{trace_id_prefix.strip()}%"))
        if start_time:
            q = q.filter(TraceSpan.start_time >= start_time)
        if end_time:
            q = q.filter(TraceSpan.start_time <= end_time)

        grouped = q.group_by(TraceSpan.trace_id)
        total = grouped.count()
        rows = (
            grouped.order_by(desc("latest_start"))
            .offset(skip)
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows], total

