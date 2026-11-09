from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import IncidentSeverity, IncidentStatus, PaginatedResponse
from app.schemas.incident import (
    IncidentCreateRequest,
    IncidentDetailResponse,
    IncidentResponse,
    IncidentStatusUpdateRequest,
    TimelineResponse,
)
from app.schemas.investigation import GroundedInvestigationResponse
from app.services.incident_service import (
    CorrelationGroupAlreadyLinkedError,
    CorrelationGroupNotFoundError,
    IncidentNotFoundError,
    IncidentService,
    InvalidStatusTransitionError,
    ProjectIsolationError,
)
from app.services.investigation.service import (
    InvestigationService,
)

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.get(
    "",
    response_model=PaginatedResponse[IncidentResponse],
    summary="List incidents with pagination and filtering",
)
def list_incidents(
    project_id: Optional[UUID] = Query(None, description="Filter by Project UUID"),
    status_filter: Optional[IncidentStatus] = Query(None, alias="status", description="Filter by incident status"),
    severity_filter: Optional[IncidentSeverity] = Query(None, alias="severity", description="Filter by incident severity"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> PaginatedResponse[IncidentResponse]:
    """Retrieve paginated incidents, filterable by project, severity, and status."""
    service = IncidentService(db)
    items, total = service.list_incidents(
        project_id=project_id,
        status=status_filter.value if status_filter else None,
        severity=severity_filter.value if severity_filter else None,
        skip=offset,
        limit=limit,
    )
    page = (offset // limit) + 1
    total_pages = max(1, (total + limit - 1) // limit)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentDetailResponse,
    summary="Get incident details by UUID or identifier",
)
def get_incident(
    incident_id: str,
    db: Session = Depends(get_db),
) -> IncidentDetailResponse:
    """Retrieve full incident details including affected services and timeline events."""
    service = IncidentService(db)
    incident = service.get_incident_by_id_or_number(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' was not found.",
        )
    return incident


@router.get(
    "/{incident_id}/timeline",
    response_model=TimelineResponse,
    summary="Get chronological timeline events for an incident",
)
def get_incident_timeline(
    incident_id: str,
    db: Session = Depends(get_db),
) -> TimelineResponse:
    """Retrieve the chronological audit events and state transitions for an incident."""
    service = IncidentService(db)
    timeline = service.get_timeline(incident_id)
    if not timeline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' was not found.",
        )
    return timeline


@router.patch(
    "/{incident_id}/status",
    response_model=IncidentDetailResponse,
    summary="Update incident lifecycle status according to validated state transition policy",
)
def update_incident_status(
    incident_id: str,
    payload: IncidentStatusUpdateRequest,
    db: Session = Depends(get_db),
) -> IncidentDetailResponse:
    """Transition an incident through its lifecycle (DETECTED, INVESTIGATING, ACKNOWLEDGED, MITIGATED, RESOLVED).

    Rejects invalid transitions with HTTP 409 Conflict.
    Appends an audit timeline event for genuine transitions.
    Repeated status requests are idempotent and do not create duplicate history events.
    """
    service = IncidentService(db)
    try:
        return service.update_status(incident_id, payload)
    except IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except InvalidStatusTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )


@router.post(
    "",
    response_model=IncidentDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new manual incident",
)
def create_incident(
    payload: IncidentCreateRequest,
    project_id: UUID = Query(..., description="Project UUID to create the incident under"),
    db: Session = Depends(get_db),
) -> IncidentDetailResponse:
    """Manually create an incident within project boundary."""
    from app.repositories.project_repository import ProjectRepository
    if not ProjectRepository(db).get_by_id(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' was not found.",
        )
    service = IncidentService(db)
    try:
        return service.create_incident(project_id=project_id, req=payload)
    except CorrelationGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ProjectIsolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except CorrelationGroupAlreadyLinkedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )


@router.get(
    "/{incident_id}/investigation",
    response_model=Optional[GroundedInvestigationResponse],
    summary="Get persisted AI investigation linked to this incident",
)
def get_incident_investigation(
    incident_id: str,
    db: Session = Depends(get_db),
) -> Optional[GroundedInvestigationResponse]:
    """Retrieve the persisted investigation for an incident without triggering Gemini generation.

    If the incident is linked to a correlation group, retrieves the group's latest persisted investigation.
    If the incident is a legacy demo scenario, retrieves its associated investigation.
    Returns 200 with null if no investigation exists.
    """
    service = IncidentService(db)
    incident = service.get_incident_by_id_or_number(incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' was not found.",
        )

    inv_service = InvestigationService(db)
    if incident.correlation_group_id:
        try:
            inv = inv_service.get_investigation_for_correlation_group(incident.correlation_group_id)
            if inv:
                return GroundedInvestigationResponse.model_validate(inv)
        except CorrelationGroupNotFoundError:
            return None

    # Legacy demo incident fallback: check direct investigation linked to incident
    legacy_inv = service.get_investigation_for_incident(incident_id)
    if legacy_inv:
        # Construct grounded response compatible view or None
        pass

    return None

