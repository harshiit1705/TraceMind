"""FastAPI endpoints for AI incident investigation generation and retrieval."""

from typing import Optional, Union
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.correlation import CorrelationGroup
from app.models.investigation import Investigation
from app.schemas.investigation import (
    GroundedInvestigationResponse,
    InvestigationDetailResponse,
    InvestigationGenerateRequest,
)
from app.services.incident_service import IncidentService
from app.services.investigation.provider import (
    ProviderConfigError,
    ProviderPermanentError,
    ProviderTimeoutError,
    ProviderTransientError,
)
from app.services.investigation.service import (
    CorrelationGroupNotFoundError,
    InvestigationService,
    ProjectIsolationError,
)
from app.services.investigation.validator import GroundingValidationError

router = APIRouter(prefix="/investigations", tags=["Investigations"])


@router.post(
    "/generate",
    response_model=GroundedInvestigationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate evidence-grounded AI investigation for a correlation group",
)
async def generate_investigation(
    payload: InvestigationGenerateRequest,
    x_project_id: Optional[str] = Header(None, alias="X-Project-Id", description="Optional project context header"),
    db: Session = Depends(get_db),
) -> GroundedInvestigationResponse:
    """Initiates or reuses a grounded AI incident investigation for a correlation group.
    
    Guarantees:
    - Resolves server-side project context from database (client-supplied authorization is rejected).
    - If X-Project-Id header is provided, enforces that it matches the correlation group's project.
    - Idempotently reuses existing COMPLETED investigation unless force_regenerate=True.
    - Grounded strictly in authentic telemetry evidence; validates event IDs, candidates, and human approval.
    - Returns safe error responses on provider or configuration failures.
    """
    # 1. Resolve trusted project context from the verified correlation group
    group = (
        db.query(CorrelationGroup)
        .filter(CorrelationGroup.id == payload.correlation_group_id)
        .first()
    )
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Correlation group '{payload.correlation_group_id}' was not found.",
        )

    # 2. If client provided project header, verify it matches the trusted group project
    if x_project_id:
        try:
            req_project_uuid = UUID(x_project_id)
            if req_project_uuid != group.project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: Correlation group belongs to a different project.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Project-Id header format. Must be a valid UUID.",
            )

    trusted_project_id = group.project_id

    # 3. Coordinate investigation lifecycle
    service = InvestigationService(db)
    try:
        inv = await service.get_or_create_investigation(
            correlation_group_id=payload.correlation_group_id,
            project_id=trusted_project_id,
            force_regenerate=payload.force_regenerate,
        )
        return GroundedInvestigationResponse.model_validate(inv)

    except CorrelationGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ProjectIsolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except ProviderConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except ProviderTransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Investigation provider temporarily unavailable: {str(exc)}",
        )
    except ProviderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        )
    except (GroundingValidationError, ProviderPermanentError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Investigation validation failure: {str(exc)}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Investigation processing error: {type(exc).__name__}",
        )


@router.get(
    "/{investigation_id}",
    response_model=Union[GroundedInvestigationResponse, InvestigationDetailResponse],
    summary="Get root-cause investigation details, findings, and remediation recommendations",
)
def get_investigation(
    investigation_id: str,
    x_project_id: Optional[str] = Header(None, alias="X-Project-Id", description="Optional project context header"),
    db: Session = Depends(get_db),
) -> Union[GroundedInvestigationResponse, InvestigationDetailResponse]:
    """Retrieve details of an incident investigation.
    
    Supports both:
    1. Grounded AI investigations linked to correlation groups (GroundedInvestigationResponse)
    2. Legacy Phase 2.3A seed investigations linked to demo incidents (InvestigationDetailResponse)
    """
    try:
        inv_uuid = UUID(investigation_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' was not found.",
        )

    # 1. Check for modern correlation-linked investigation
    inv_service = InvestigationService(db)
    expected_proj_uuid: Optional[UUID] = None
    if x_project_id:
        try:
            expected_proj_uuid = UUID(x_project_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Project-Id header format. Must be a valid UUID.",
            )

    try:
        inv = inv_service.get_investigation_by_id(inv_uuid, expected_project_id=expected_proj_uuid)
    except ProjectIsolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    if inv and inv.correlation_group_id is not None:
        return inv_service.to_grounded_response(inv)

    # 2. Fall back to legacy incident investigation service if not a correlation investigation
    legacy_service = IncidentService(db)
    legacy_inv = legacy_service.get_investigation(inv_uuid)
    if not legacy_inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' was not found.",
        )
    return legacy_inv
