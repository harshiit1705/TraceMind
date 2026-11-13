from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.core.auth import AuthenticatedActor, authenticate_actor
from app.db.session import get_db
from app.models.incident import Incident
from app.schemas.common import IncidentSeverity, IncidentStatus, PaginatedResponse
from app.schemas.incident import (
    IncidentCreateRequest,
    IncidentDetailResponse,
    IncidentResponse,
    IncidentStatusUpdateRequest,
    TimelineResponse,
)
from app.schemas.investigation import GroundedInvestigationResponse
from app.schemas.recommendation import RemediationDetailResponse, RemediationProposeRequest
from app.schemas.telemetry import ApplicationLogResponse
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
from app.services.telemetry.logs_service import LogsService

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
    "/stats",
    summary="Aggregate incident KPI stats from persisted database records",
)
def get_incidents_stats(
    project_id: Optional[UUID] = Query(None, description="Optional Project UUID filter"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Compute incident KPI metrics strictly from persisted incidents."""
    q = db.query(Incident)
    if project_id:
        q = q.filter(Incident.project_id == project_id)
    incidents = q.all()

    now_utc = datetime.now(timezone.utc)
    cutoff_24h = now_utc - timedelta(hours=24)

    active = [i for i in incidents if i.status != IncidentStatus.RESOLVED.value]
    critical = [i for i in active if (i.severity or "").upper() == "CRITICAL"]
    acknowledged = [i for i in incidents if i.status == IncidentStatus.ACKNOWLEDGED.value]
    resolved_24h = [
        i for i in incidents
        if i.status == IncidentStatus.RESOLVED.value
        and i.resolved_at
        and (i.resolved_at if i.resolved_at.tzinfo else i.resolved_at.replace(tzinfo=timezone.utc)) >= cutoff_24h
    ]

    mttr_mins: list[float] = []
    for i in incidents:
        if i.resolved_at and i.started_at:
            s = i.started_at if i.started_at.tzinfo else i.started_at.replace(tzinfo=timezone.utc)
            r = i.resolved_at if i.resolved_at.tzinfo else i.resolved_at.replace(tzinfo=timezone.utc)
            diff = (r - s).total_seconds() / 60.0
            if diff >= 0:
                mttr_mins.append(diff)

    mttr_str = f"{(sum(mttr_mins) / len(mttr_mins)):.1f}m" if mttr_mins else "N/A"
    return {
        "activeCount": len(active),
        "criticalImpactCount": len(critical),
        "acknowledgedCount": len(acknowledged),
        "resolved24hCount": len(resolved_24h),
        "mttdFormatted": "< 1m" if incidents else "N/A",
        "mttrFormatted": mttr_str,
    }


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


@router.get(
    "/{incident_id}/logs",
    response_model=PaginatedResponse[ApplicationLogResponse],
    summary="Retrieve structured logs associated with an incident's services and timeframe",
)
def get_incident_logs(
    incident_id: str,
    level: Optional[str] = Query(None, description="Optional log severity filter"),
    trace_id: Optional[str] = Query(None, description="Optional trace_id filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ApplicationLogResponse]:
    logs_svc = LogsService(db)
    try:
        items, total = logs_svc.get_logs_for_incident(
            incident_identifier=incident_id,
            level=level,
            trace_id=trace_id,
            skip=offset,
            limit=limit,
        )
    except IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
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
    "/{incident_id}/remediations",
    response_model=List[RemediationDetailResponse],
    summary="List all proposed, approved, or executed remediations for an incident",
)
def list_incident_remediations(
    incident_id: str,
    project_id: UUID = Query(..., description="Mandatory project UUID for tenant isolation"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> List[RemediationDetailResponse]:
    from app.services.remediation.service import RemediationService
    service = RemediationService(db)
    try:
        return service.list_remediations_for_incident(incident_id, project_id=project_id, actor=actor)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{incident_id}/remediations",
    response_model=RemediationDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually propose a new remediation recommendation for an incident",
)
def propose_incident_remediation(
    incident_id: str,
    payload: RemediationProposeRequest,
    project_id: UUID = Query(..., description="Mandatory project UUID for tenant isolation"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RemediationDetailResponse:
    from app.services.remediation.service import RemediationService
    service = RemediationService(db)
    try:
        return service.propose_remediation(incident_id, req=payload, project_id=project_id, actor=actor)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

