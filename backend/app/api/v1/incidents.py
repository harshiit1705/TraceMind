from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import IncidentSeverity, IncidentStatus, PaginatedResponse
from app.schemas.incident import (
    IncidentDetailResponse,
    IncidentResponse,
    TimelineResponse,
)
from app.services.incident_service import IncidentService

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
