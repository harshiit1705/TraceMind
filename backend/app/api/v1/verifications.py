"""API router for Phase 5: Telemetry-Based Recovery Verification."""

import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedActor, authenticate_actor
from app.db.session import get_db
from app.models.incident import Incident
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


def _resolve_incident_project_id(db: Session, incident_id: str, project_id: Optional[UUID]) -> UUID:
    """Resolves project_id from query parameter or auto-discovers from incident record."""
    if project_id is not None:
        return project_id
    query = db.query(Incident)
    try:
        val_uuid = UUID(incident_id)
        inc = query.filter(Incident.id == val_uuid).first()
    except (ValueError, TypeError):
        inc = query.filter(Incident.incident_number == incident_id).first()
    if not inc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Incident '{incident_id}' not found.")
    return inc.project_id


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
    project_id: Optional[UUID] = Query(None, description="Optional project UUID; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RecoveryVerificationResponse:
    effective_project_id = _resolve_incident_project_id(db, incident_id, project_id)
    service = RecoveryVerificationService(db)
    try:
        return service.start_verification(
            incident_id=incident_id,
            remediation_id=remediation_id,
            project_id=effective_project_id,
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
@router.get(
    "/verifications/incident/{incident_id}",
    response_model=List[RecoveryVerificationResponse],
    summary="Alias: List historical recovery verification records for an incident",
    include_in_schema=False,
)
def list_incident_verifications(
    incident_id: str,
    project_id: Optional[UUID] = Query(None, description="Optional project UUID; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> List[RecoveryVerificationResponse]:
    effective_project_id = _resolve_incident_project_id(db, incident_id, project_id)
    service = RecoveryVerificationService(db)
    try:
        return service.list_verifications_for_incident(
            incident_id=incident_id,
            project_id=effective_project_id,
            actor=actor,
        )
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def _resolve_verification_project_id(db: Session, verification_id: UUID, project_id: Optional[UUID]) -> UUID:
    """Resolves project_id from query parameter or auto-discovers from verification record."""
    if project_id is not None:
        return project_id
    from app.models.recovery_verification import RecoveryVerification
    ver = db.query(RecoveryVerification).filter(RecoveryVerification.id == verification_id).first()
    if not ver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Recovery verification '{verification_id}' not found.")
    return ver.project_id


@router.get(
    "/verifications/{verification_id}",
    response_model=RecoveryVerificationResponse,
    summary="Get details of a specific recovery verification record",
)
def get_recovery_verification(
    verification_id: UUID,
    project_id: Optional[UUID] = Query(None, description="Optional project UUID; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RecoveryVerificationResponse:
    effective_project_id = _resolve_verification_project_id(db, verification_id, project_id)
    service = RecoveryVerificationService(db)
    try:
        return service.get_verification(
            verification_id=verification_id,
            project_id=effective_project_id,
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
    project_id: Optional[UUID] = Query(None, description="Optional project UUID; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RecoveryVerificationResponse:
    effective_project_id = _resolve_verification_project_id(db, verification_id, project_id)
    service = RecoveryVerificationService(db)
    try:
        return service.retry_verification(
            verification_id=verification_id,
            project_id=effective_project_id,
            actor=actor,
            req=payload,
        )
    except (IncidentNotFoundError, RemediationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InvalidRemediationStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
