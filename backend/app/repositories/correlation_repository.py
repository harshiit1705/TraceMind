"""Repository for persisting and querying correlation groups and ranked root-cause candidates."""

from typing import List, Optional
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from app.models.correlation import (
    CorrelationEventAssociation,
    CorrelationGroup,
    RootCauseCandidate,
)
from app.schemas.correlation import CorrelationGroupResponse


class CorrelationRepository:
    """Handles transactional persistence and retrieval of correlation entities."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, group_id: UUID) -> Optional[CorrelationGroup]:
        return (
            self.db.query(CorrelationGroup)
            .filter(CorrelationGroup.id == group_id)
            .first()
        )

    def get_by_key(self, project_id: UUID, correlation_key: str) -> Optional[CorrelationGroup]:
        return (
            self.db.query(CorrelationGroup)
            .filter(
                CorrelationGroup.project_id == project_id,
                CorrelationGroup.correlation_key == correlation_key,
            )
            .first()
        )

    def list_by_project(
        self,
        project_id: UUID,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[CorrelationGroup]:
        query = self.db.query(CorrelationGroup).filter(CorrelationGroup.project_id == project_id)
        if status:
            query = query.filter(CorrelationGroup.status == status.upper())
        return (
            query.order_by(CorrelationGroup.time_window_start.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def find_encompassing_active_group(self, project_id: UUID, event_ids: List[UUID]) -> Optional[CorrelationGroup]:
        """Find an existing ACTIVE group whose events are a superset of the given event_ids."""
        active_groups = (
            self.db.query(CorrelationGroup)
            .filter(
                CorrelationGroup.project_id == project_id,
                CorrelationGroup.status == "ACTIVE",
            )
            .all()
        )
        target_ids = set(event_ids)
        for ag in active_groups:
            ag_event_ids = {assoc.anomaly_event_id for assoc in ag.event_associations}
            if target_ids.issubset(ag_event_ids):
                return ag
        return None

    def supersede_subsumed_active_groups(self, project_id: UUID, new_event_ids: List[UUID]) -> List[CorrelationGroup]:
        """Mark any existing ACTIVE groups whose events are a strict subset of new_event_ids as SUPERSEDED."""
        active_groups = (
            self.db.query(CorrelationGroup)
            .filter(
                CorrelationGroup.project_id == project_id,
                CorrelationGroup.status == "ACTIVE",
            )
            .all()
        )
        superseded: List[CorrelationGroup] = []
        target_ids = set(new_event_ids)
        for ag in active_groups:
            ag_event_ids = {assoc.anomaly_event_id for assoc in ag.event_associations}
            if ag_event_ids.issubset(target_ids) and ag_event_ids != target_ids:
                ag.status = "SUPERSEDED"
                superseded.append(ag)
        return superseded

    def persist_group(self, evaluated: CorrelationGroupResponse, commit: bool = True) -> CorrelationGroup:
        """Persist a newly discovered correlation group or return existing if already recorded.
        
        Guarantees:
        - Atomic persistence of group, event associations, and ranked candidates.
        - Idempotent repeated evaluation: identical correlation_key returns existing record without duplicate insertion.
        - Subsumption handling: if an existing ACTIVE group already encompasses all events, return it.
        - Supersession lifecycle: if this group represents an expanded cascade containing all events of prior
          narrower ACTIVE group(s), mark those earlier groups as SUPERSEDED.
        - Transaction rollback on any database failure.
        """
        # 1. Idempotency check: exact match
        existing = self.get_by_key(evaluated.project_id, evaluated.correlation_key)
        if existing:
            existing._superseded_groups = []
            return existing

        target_event_ids = [ev.event_id for ev in evaluated.participating_events]

        # 2. Subsumption check: already contained in an active encompassing group
        encompassing = self.find_encompassing_active_group(evaluated.project_id, target_event_ids)
        if encompassing:
            encompassing._superseded_groups = []
            return encompassing

        # 3. Supersession check: mark narrower active groups as SUPERSEDED
        superseded = self.supersede_subsumed_active_groups(evaluated.project_id, target_event_ids)

        new_group_id = uuid4()
        group_row = CorrelationGroup(
            id=new_group_id,
            project_id=evaluated.project_id,
            correlation_key=evaluated.correlation_key,
            time_window_start=evaluated.time_window_start,
            time_window_end=evaluated.time_window_end,
            status=evaluated.status or "ACTIVE",
            summary=evaluated.summary,
            confidence_score=evaluated.confidence_score,
            topology_complete=evaluated.topology_complete,
        )
        self.db.add(group_row)

        # 2. Add event associations
        for ev in evaluated.participating_events:
            assoc = CorrelationEventAssociation(
                correlation_group_id=new_group_id,
                anomaly_event_id=ev.event_id,
                relevance_score=ev.relevance_score,
                correlation_reason=ev.correlation_reason,
            )
            self.db.add(assoc)

        # 3. Add ranked root cause candidates
        for c in evaluated.ranked_candidates:
            cand_row = RootCauseCandidate(
                id=uuid4(),
                correlation_group_id=new_group_id,
                service_id=c.service_id,
                rank=c.rank,
                score=c.score,
                confidence=c.confidence.value,
                is_probable_root_cause=c.is_probable_root_cause,
                temporal_precedence_score=c.breakdown.temporal_precedence.score,
                topological_score=c.breakdown.topological_position.score,
                blast_radius_score=c.breakdown.blast_radius.score,
                severity_score=c.breakdown.severity_magnitude.score,
                reasons_json=c.model_dump(mode="json"),
            )
            self.db.add(cand_row)

        if commit:
            self.db.commit()
            self.db.refresh(group_row)
        else:
            self.db.flush()
        group_row._superseded_groups = superseded
        return group_row

