"""API router for human-approved incident remediation workflow.

Hardened in Phase 4.1:
- SEC-01: Mandatory operator authentication on all mutation and retrieval routes.
- SEC-02: Mandatory project_id query parameter enforced for tenant isolation.
"""

import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedActor, authenticate_actor
from app.db.session import get_db
from app.models.recommendation import Recommendation
from app.schemas.recommendation import (
    RemediationApproveRequest,
    RemediationCancelRequest,
    RemediationDetailResponse,
    RemediationExecuteRequest,
    RemediationReconcileRequest,
    RemediationRejectRequest,
)
from app.services.incident_service import IncidentNotFoundError, ProjectIsolationError
from app.services.remediation.exceptions import (
    ActionNotAllowlistedError,
    DuplicateExecutionError,
    InvalidRemediationStateError,
    ParameterValidationError,
    RemediationExecutionError,
    RemediationNotFoundError,
    RemediationTimeoutError,
)
from app.services.remediation.service import RemediationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/remediations", tags=["remediations"])


def _resolve_remediation_project_id(db: Session, remediation_id: UUID, project_id: Optional[UUID]) -> UUID:
    """Resolves project_id from query parameter or auto-discovers from remediation record."""
    if project_id is not None:
        return project_id
    rec = db.query(Recommendation).filter(Recommendation.id == remediation_id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Remediation '{remediation_id}' not found.")
    return rec.project_id


@router.get(
    "/{remediation_id}",
    response_model=RemediationDetailResponse,
    summary="Get remediation recommendation details by ID",
)
def get_remediation(
    remediation_id: UUID,
    project_id: Optional[UUID] = Query(None, description="Optional project UUID for tenant isolation; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RemediationDetailResponse:
    effective_project_id = _resolve_remediation_project_id(db, remediation_id, project_id)
    service = RemediationService(db)
    try:
        return service.get_remediation(remediation_id, project_id=effective_project_id, actor=actor)
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{remediation_id}/approve",
    response_model=RemediationDetailResponse,
    summary="Explicitly approve a remediation recommendation",
)
def approve_remediation(
    remediation_id: UUID,
    payload: RemediationApproveRequest,
    project_id: Optional[UUID] = Query(None, description="Optional project UUID for tenant isolation; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RemediationDetailResponse:
    effective_project_id = _resolve_remediation_project_id(db, remediation_id, project_id)
    service = RemediationService(db)
    try:
        return service.approve_remediation(remediation_id, req=payload, project_id=effective_project_id, actor=actor)
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidRemediationStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{remediation_id}/reject",
    response_model=RemediationDetailResponse,
    summary="Explicitly reject a remediation recommendation",
)
def reject_remediation(
    remediation_id: UUID,
    payload: RemediationRejectRequest,
    project_id: Optional[UUID] = Query(None, description="Optional project UUID for tenant isolation; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RemediationDetailResponse:
    effective_project_id = _resolve_remediation_project_id(db, remediation_id, project_id)
    service = RemediationService(db)
    try:
        return service.reject_remediation(remediation_id, req=payload, project_id=effective_project_id, actor=actor)
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidRemediationStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{remediation_id}/cancel",
    response_model=RemediationDetailResponse,
    summary="Cancel a proposed or approved remediation",
)
def cancel_remediation(
    remediation_id: UUID,
    payload: RemediationCancelRequest,
    project_id: Optional[UUID] = Query(None, description="Optional project UUID for tenant isolation; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RemediationDetailResponse:
    effective_project_id = _resolve_remediation_project_id(db, remediation_id, project_id)
    service = RemediationService(db)
    try:
        return service.cancel_remediation(remediation_id, req=payload, project_id=effective_project_id, actor=actor)
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidRemediationStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{remediation_id}/execute",
    response_model=RemediationDetailResponse,
    summary="Execute an approved remediation action",
)
def execute_remediation(
    remediation_id: UUID,
    payload: RemediationExecuteRequest,
    project_id: Optional[UUID] = Query(None, description="Optional project UUID for tenant isolation; auto-resolved if omitted"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RemediationDetailResponse:
    effective_project_id = _resolve_remediation_project_id(db, remediation_id, project_id)
    service = RemediationService(db)
    try:
        return service.execute_remediation(remediation_id, req=payload, project_id=effective_project_id, actor=actor)
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidRemediationStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except DuplicateExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ActionNotAllowlistedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ParameterValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except RemediationTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc))
    except RemediationExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post(
    "/{remediation_id}/reconcile",
    response_model=RemediationDetailResponse,
    summary="Reconcile an abandoned or expired EXECUTING remediation",
)
def reconcile_remediation(
    remediation_id: UUID,
    payload: RemediationReconcileRequest,
    project_id: UUID = Query(..., description="Mandatory project UUID for tenant isolation"),
    actor: AuthenticatedActor = Depends(authenticate_actor),
    db: Session = Depends(get_db),
) -> RemediationDetailResponse:
    service = RemediationService(db)
    try:
        return service.reconcile_stuck_execution(remediation_id, req=payload, project_id=project_id, actor=actor)
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidRemediationStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ProjectIsolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
