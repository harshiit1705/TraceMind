"""FastAPI endpoints for anomaly correlation evaluation and root-cause candidate ranking."""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.correlation import (
    CorrelationEvaluationRequest,
    CorrelationEvaluationResponse,
    CorrelationGroupResponse,
    RootCauseCandidateResponse,
)
from app.services.correlation.service import (
    CorrelationGroupNotFoundError,
    CorrelationService,
    ProjectNotFoundError,
)

router = APIRouter(prefix="/correlations", tags=["Anomaly Correlations & Root Cause"])


@router.post(
    "/evaluate",
    response_model=CorrelationEvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate and correlate cross-service anomalies within a project and time window",
)
def evaluate_correlations(
    payload: CorrelationEvaluationRequest,
    db: Session = Depends(get_db),
) -> CorrelationEvaluationResponse:
    """Evaluate telemetry anomalies across services, cluster related cascades, and rank probable root causes.
    
    Guarantees:
    - Strictly isolates evaluation within project boundaries.
    - Idempotently prevents duplicate correlation groups on repeated evaluation.
    - Transparently explains causal dimension scoring (temporal, topological, blast radius, severity).
    - Distinguishes correlation from proven causation.
    """
    service = CorrelationService(db)
    try:
        return service.evaluate_and_persist(payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.get(
    "",
    response_model=List[CorrelationGroupResponse],
    summary="List correlation groups for a project",
)
def list_correlations(
    project_id: UUID = Query(..., description="Project UUID to list correlations for"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (ACTIVE, RESOLVED, etc.)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> List[CorrelationGroupResponse]:
    """Retrieve persisted correlation groups for a project ordered by time window."""
    service = CorrelationService(db)
    try:
        return service.list_groups(
            project_id=project_id,
            status=status_filter,
            skip=skip,
            limit=limit,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.get(
    "/{correlation_id}",
    response_model=CorrelationGroupResponse,
    summary="Retrieve an individual correlation group with its evidence",
)
def get_correlation(
    correlation_id: UUID,
    db: Session = Depends(get_db),
) -> CorrelationGroupResponse:
    """Retrieve a specific correlation group with participating anomaly events and ranked root-cause candidates."""
    service = CorrelationService(db)
    try:
        return service.get_group(correlation_id)
    except CorrelationGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.get(
    "/{correlation_id}/candidates",
    response_model=List[RootCauseCandidateResponse],
    summary="Retrieve ranked root-cause candidates for a correlation group",
)
def get_root_cause_candidates(
    correlation_id: UUID,
    db: Session = Depends(get_db),
) -> List[RootCauseCandidateResponse]:
    """Retrieve ranked probable root causes with scoring breakdown and limitation notices."""
    service = CorrelationService(db)
    try:
        return service.get_ranked_candidates(correlation_id)
    except CorrelationGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

