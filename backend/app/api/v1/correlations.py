"""FastAPI endpoints for anomaly correlation evaluation and root-cause candidate ranking."""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.correlation import (
    CorrelationEvaluationRequest,
    CorrelationEvaluationResponse,
    CorrelationGroupResponse,
    RootCauseCandidateResponse,
)
from app.schemas.investigation import GroundedInvestigationResponse
from app.services.correlation.service import (
    CorrelationGroupNotFoundError,
    CorrelationService,
    ProjectNotFoundError,
)
from app.services.investigation.service import (
    CorrelationGroupNotFoundError as InvCorrelationGroupNotFoundError,
    InvestigationService,
    ProjectIsolationError,
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


@router.get(
    "/{correlation_group_id}/investigation",
    response_model=Optional[GroundedInvestigationResponse],
    status_code=status.HTTP_200_OK,
    summary="Get latest persisted AI investigation for a correlation group without generation",
)
def get_correlation_investigation(
    correlation_group_id: UUID,
    x_project_id: Optional[str] = Header(None, alias="X-Project-Id", description="Optional project context header"),
    db: Session = Depends(get_db),
) -> Optional[GroundedInvestigationResponse]:
    """Retrieve the latest persisted investigation for a correlation group in a strictly read-only manner.
    
    Guarantees:
    - Never invokes Gemini or AI provider.
    - Never creates or updates database records.
    - Validates that correlation group exists (404 if missing).
    - Validates project isolation if X-Project-Id header is supplied (403 if mismatched).
    - Returns 200 with null body if no investigation exists for the group.
    - Returns full GroundedInvestigationResponse if an investigation exists (COMPLETED, FAILED, RUNNING, PENDING).
    """
    expected_proj_uuid: Optional[UUID] = None
    if x_project_id:
        try:
            expected_proj_uuid = UUID(x_project_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Project-Id header format. Must be a valid UUID.",
            )

    inv_service = InvestigationService(db)
    try:
        inv = inv_service.get_investigation_for_correlation_group(
            correlation_group_id,
            expected_project_id=expected_proj_uuid,
        )
    except (CorrelationGroupNotFoundError, InvCorrelationGroupNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ProjectIsolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    if not inv:
        return None

    return GroundedInvestigationResponse.model_validate(inv)


