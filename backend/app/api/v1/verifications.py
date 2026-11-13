"""API router for Phase 5: Telemetry-Based Recovery Verification."""

import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedActor, authenticate_actor
from app.db.session import get_db
from app.schemas.recovery_verification import (
    RecoveryVerificationRequest,
    RecoveryVerificationResponse,
)
from app.services.incident_service import IncidentNotFoundError, ProjectIsolationError
from app.services.recovery.verification_service import RecoveryVerificationService
from app.services.remediation.exceptions import (
    InvalidRemediationStateError,
    RemediationNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recovery-verification"])


@router.post(
    "/incidents/{incident_id}/remediations/{remediation_id}/verify",
    response_model=RecoveryVerificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger telemetry-grounded recovery verification for an executed remediation",
)
def verify_remediation_recovery(
    incident_id: str,
    remediation_id: UUID,
    payload: RecoveryVerificationRequest = RecoveryVerificationRequest(),
    project_id: UUID = Query(..., description="Mandatory project UUID for tenant isolation"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RecoveryVerificationResponse:
    service = RecoveryVerificationService(db)
    try:
        return service.start_verification(
            incident_id=incident_id,
            remediation_id=remediation_id,
            project_id=project_id,
            actor=actor,
            req=payload,
        )
    except (IncidentNotFoundError, RemediationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InvalidRemediationStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/incidents/{incident_id}/verifications",
    response_model=List[RecoveryVerificationResponse],
    summary="List historical recovery verification records for an incident",
)
def list_incident_verifications(
    incident_id: str,
    project_id: UUID = Query(..., description="Mandatory project UUID for tenant isolation"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> List[RecoveryVerificationResponse]:
    service = RecoveryVerificationService(db)
    try:
        return service.list_verifications_for_incident(
            incident_id=incident_id,
            project_id=project_id,
            actor=actor,
        )
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get(
    "/verifications/{verification_id}",
    response_model=RecoveryVerificationResponse,
    summary="Get details of a specific recovery verification record",
)
def get_recovery_verification(
    verification_id: UUID,
    project_id: UUID = Query(..., description="Mandatory project UUID for tenant isolation"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RecoveryVerificationResponse:
    service = RecoveryVerificationService(db)
    try:
        return service.get_verification(
            verification_id=verification_id,
            project_id=project_id,
            actor=actor,
        )
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/verifications/{verification_id}/retry",
    response_model=RecoveryVerificationResponse,
    summary="Retry a recovery verification using fresh post-remediation telemetry",
)
def retry_recovery_verification(
    verification_id: UUID,
    payload: RecoveryVerificationRequest = RecoveryVerificationRequest(),
    project_id: UUID = Query(..., description="Mandatory project UUID for tenant isolation"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RecoveryVerificationResponse:
    service = RecoveryVerificationService(db)
    try:
        return service.retry_verification(
            verification_id=verification_id,
            project_id=project_id,
            actor=actor,
            req=payload,
        )
    except (IncidentNotFoundError, RemediationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InvalidRemediationStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
