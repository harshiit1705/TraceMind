"""Repository for persisting anomaly baselines and events in PostgreSQL."""

import hashlib
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models.anomaly import AnomalyBaseline, AnomalyEvent


def compute_advisory_lock_key(project_id: UUID, service_id: UUID, metric_name: str) -> int:
    """Deterministically hash (project_id, service_id, metric_name) into a 64-bit signed int."""
    norm_metric = metric_name.strip().lower()
    raw = f"{project_id}:{service_id}:{norm_metric}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


class AnomalyBaselineRepository:
    """Repository handling database operations for anomaly baselines."""

    def __init__(self, db: Session):
        self.db = db

    def acquire_advisory_lock(
        self,
        project_id: UUID,
        service_id: UUID,
        metric_name: str,
    ) -> None:
        """Acquire a transaction-level PostgreSQL advisory lock for the baseline identity.

        Serializes concurrent first-time baseline creation before row existence checks.
        Automatically released upon transaction commit or rollback.
        """
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            lock_key = compute_advisory_lock_key(project_id, service_id, metric_name)
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": lock_key},
            )

    def get(
        self,
        project_id: UUID,
        service_id: UUID,
        metric_name: str,
        for_update: bool = False,
    ) -> Optional[AnomalyBaseline]:
        """Fetch baseline for a project/service/canonical-metric tuple with optional row locking."""
        norm_metric = metric_name.strip().lower()
        query = self.db.query(AnomalyBaseline).filter(
            AnomalyBaseline.project_id == project_id,
            AnomalyBaseline.service_id == service_id,
            AnomalyBaseline.metric_name == norm_metric,
        )
        # Apply PostgreSQL row-level locking when requested
        if for_update and self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            query = query.with_for_update()

        return query.first()

    def get_by_id(self, baseline_id: UUID) -> Optional[AnomalyBaseline]:
        return self.db.query(AnomalyBaseline).filter(AnomalyBaseline.id == baseline_id).first()

    def create(self, baseline: AnomalyBaseline) -> AnomalyBaseline:
        self.db.add(baseline)
        self.db.flush()
        return baseline

    def update(self, baseline: AnomalyBaseline) -> AnomalyBaseline:
        self.db.add(baseline)
        self.db.flush()
        return baseline

    def delete(self, baseline: AnomalyBaseline) -> None:
        self.db.delete(baseline)
        self.db.flush()


class AnomalyEventRepository:
    """Repository handling database operations for confirmed anomaly events."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, event: AnomalyEvent) -> AnomalyEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def get_by_id(self, event_id: UUID) -> Optional[AnomalyEvent]:
        return self.db.query(AnomalyEvent).filter(AnomalyEvent.id == event_id).first()

    def list_by_service(
        self,
        project_id: UUID,
        service_id: UUID,
        metric_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[AnomalyEvent]:
        query = self.db.query(AnomalyEvent).filter(
            AnomalyEvent.project_id == project_id,
            AnomalyEvent.service_id == service_id,
        )
        if metric_name:
            query = query.filter(AnomalyEvent.metric_name == metric_name.strip().lower())
        return query.order_by(AnomalyEvent.occurred_at.desc()).limit(limit).all()

    def get_by_source_event_id(
        self,
        project_id: UUID,
        service_id: UUID,
        metric_name: str,
        source_event_id: str,
    ) -> Optional[AnomalyEvent]:
        return (
            self.db.query(AnomalyEvent)
            .filter(
                AnomalyEvent.project_id == project_id,
                AnomalyEvent.service_id == service_id,
                AnomalyEvent.metric_name == metric_name.strip().lower(),
                AnomalyEvent.source_event_id == source_event_id.strip(),
            )
            .first()
        )

    def get_by_timestamp(
        self,
        project_id: UUID,
        service_id: UUID,
        metric_name: str,
        occurred_at: datetime,
    ) -> Optional[AnomalyEvent]:
        return (
            self.db.query(AnomalyEvent)
            .filter(
                AnomalyEvent.project_id == project_id,
                AnomalyEvent.service_id == service_id,
                AnomalyEvent.metric_name == metric_name.strip().lower(),
                AnomalyEvent.occurred_at == occurred_at,
            )
            .first()
        )

