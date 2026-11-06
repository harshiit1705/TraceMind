"""Application service coordinating correlation evaluation, persistence, and querying."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.correlation import CorrelationGroup, RootCauseCandidate
from app.repositories.correlation_repository import CorrelationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.service_repository import ServiceRepository
from app.schemas.correlation import (
    CorrelationEvaluationRequest,
    CorrelationEvaluationResponse,
    CorrelationGroupResponse,
    CorrelatedEventSummary,
    RootCauseCandidateResponse,
)
from app.services.correlation.engine import CorrelationEngine


class ProjectNotFoundError(Exception):
    """Raised when the specified project does not exist."""
    pass


class CorrelationGroupNotFoundError(Exception):
    """Raised when the requested correlation group does not exist."""
    pass


class CorrelationService:
    """Application service managing cross-service anomaly correlation and causal candidate ranking."""

    def __init__(self, db: Session):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.service_repo = ServiceRepository(db)
        self.correlation_repo = CorrelationRepository(db)
        self.engine = CorrelationEngine(db)

    def evaluate_and_persist(
        self,
        request: CorrelationEvaluationRequest,
    ) -> CorrelationEvaluationResponse:
        """Evaluate cross-service anomaly correlations within project boundary and persist results."""
        project = self.project_repo.get_by_id(request.project_id)
        if not project:
            raise ProjectNotFoundError(f"Project '{request.project_id}' was not found.")

        # Run correlation engine
        discovered_groups = self.engine.evaluate(
            project_id=request.project_id,
            start_time=request.start_time,
            end_time=request.end_time,
            config=request.config,
        )

        persisted_group_responses: List[CorrelationGroupResponse] = []
        seen_group_ids = set()
        total_anomalies_evaluated = 0

        for group_resp in discovered_groups:
            total_anomalies_evaluated += group_resp.events_count
            persisted_row = self.correlation_repo.persist_group(group_resp)

            # Avoid duplicates if multiple evaluated clusters resolve to the same encompassing group
            if persisted_row.id not in seen_group_ids:
                seen_group_ids.add(persisted_row.id)
                persisted_resp = self._to_group_response(persisted_row)
                persisted_group_responses.append(persisted_resp)

        now_utc = datetime.now(timezone.utc)
        start_t = request.start_time or (
            persisted_group_responses[0].time_window_start
            if persisted_group_responses
            else now_utc
        )
        end_t = request.end_time or now_utc

        return CorrelationEvaluationResponse(
            project_id=request.project_id,
            evaluated_at=now_utc,
            time_window_start=start_t,
            time_window_end=end_t,
            total_anomalies_evaluated=total_anomalies_evaluated,
            correlation_groups_count=len(persisted_group_responses),
            groups=persisted_group_responses,
        )

    def list_groups(
        self,
        project_id: UUID,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[CorrelationGroupResponse]:
        """List persisted correlation groups for a project."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

        group_rows = self.correlation_repo.list_by_project(
            project_id=project_id,
            status=status,
            skip=skip,
            limit=limit,
        )

        return [self._to_group_response(row) for row in group_rows]

    def get_group(self, correlation_id: UUID) -> CorrelationGroupResponse:
        """Retrieve a specific correlation group with complete event and candidate evidence."""
        row = self.correlation_repo.get_by_id(correlation_id)
        if not row:
            raise CorrelationGroupNotFoundError(f"Correlation group '{correlation_id}' was not found.")
        return self._to_group_response(row)

    def get_ranked_candidates(self, correlation_id: UUID) -> List[RootCauseCandidateResponse]:
        """Retrieve ranked root-cause candidates for a correlation group."""
        group = self.get_group(correlation_id)
        return group.ranked_candidates

    def _to_group_response(self, row: CorrelationGroup) -> CorrelationGroupResponse:
        """Convert SQLAlchemy CorrelationGroup model to Pydantic CorrelationGroupResponse."""
        participating_events: List[CorrelatedEventSummary] = []
        for assoc in row.event_associations:
            ev = assoc.anomaly_event
            svc = ev.service if ev else None
            participating_events.append(
                CorrelatedEventSummary(
                    event_id=assoc.anomaly_event_id,
                    service_id=ev.service_id if ev else UUID(int=0),
                    service_name=svc.name if svc else "Unknown Service",
                    service_identifier=svc.identifier if svc else "unknown",
                    metric_name=ev.metric_name if ev else "unknown",
                    observed_value=ev.observed_value if ev else 0.0,
                    expected_baseline=ev.expected_baseline if ev else None,
                    deviation_pct=ev.deviation_pct if ev else None,
                    severity=ev.severity if ev else "medium",
                    occurred_at=ev.occurred_at if ev else assoc.created_at,
                    relevance_score=assoc.relevance_score,
                    correlation_reason=assoc.correlation_reason,
                )
            )

        ranked_candidates: List[RootCauseCandidateResponse] = []
        for cand in row.root_cause_candidates:
            # Reconstruct from stored reasons_json if available
            cand_dict = cand.reasons_json
            if cand_dict and "breakdown" in cand_dict:
                ranked_candidates.append(RootCauseCandidateResponse(**cand_dict))
            else:
                svc = cand.service
                from app.schemas.correlation import (
                    RankingConfidence,
                    RankingDimensionScore,
                    RootCauseRankingBreakdown,
                )
                ranked_candidates.append(
                    RootCauseCandidateResponse(
                        rank=cand.rank,
                        service_id=cand.service_id,
                        service_slug=svc.slug if svc else "unknown",
                        service_name=svc.name if svc else "Unknown Service",
                        service_identifier=svc.identifier if svc else "unknown",
                        score=cand.score,
                        confidence=RankingConfidence(cand.confidence),
                        is_probable_root_cause=cand.is_probable_root_cause,
                        breakdown=RootCauseRankingBreakdown(
                            temporal_precedence=RankingDimensionScore(
                                score=cand.temporal_precedence_score,
                                weight=0.35,
                                weighted_score=round(cand.temporal_precedence_score * 0.35, 4),
                                reason="Temporal precedence score",
                            ),
                            topological_position=RankingDimensionScore(
                                score=cand.topological_score,
                                weight=0.35,
                                weighted_score=round(cand.topological_score * 0.35, 4),
                                reason="Topological position score",
                            ),
                            blast_radius=RankingDimensionScore(
                                score=cand.blast_radius_score,
                                weight=0.15,
                                weighted_score=round(cand.blast_radius_score * 0.15, 4),
                                reason="Blast radius score",
                            ),
                            severity_magnitude=RankingDimensionScore(
                                score=cand.severity_score,
                                weight=0.15,
                                weighted_score=round(cand.severity_score * 0.15, 4),
                                reason="Severity score",
                            ),
                        ),
                        supporting_evidence=[],
                        limitations=[],
                    )
                )

        return CorrelationGroupResponse(
            id=row.id,
            project_id=row.project_id,
            correlation_key=row.correlation_key,
            time_window_start=row.time_window_start,
            time_window_end=row.time_window_end,
            status=row.status,
            summary=row.summary,
            confidence_score=row.confidence_score,
            topology_complete=row.topology_complete,
            events_count=len(participating_events),
            participating_events=participating_events,
            ranked_candidates=ranked_candidates,
            created_at=row.created_at,
        )

