"""Remediation Service: Manages human approval lifecycle, audit trails, and safe action execution.

Hardened in Phase 4.1:
- SEC-01: Authenticated operator identity required for all transitions. Zero trust in client body identity.
- SEC-02: Mandatory server-side project boundary enforcement; project_id=None rejected.
- REL-01: Atomic conditional state claims preventing concurrent double-execution.
- REL-02: Strict execution mode enforcement; real microservice failures NEVER fallback to simulated success.
- REL-03: Reliable failure audit event persistence across rollback boundaries.
- REL-04: Concurrency lease tracking and administrative reconciliation for stuck EXECUTING states.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedActor
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.investigation import Investigation
from app.models.recommendation import Recommendation
from app.schemas.recommendation import (
    AllowlistedAction,
    RecommendationResponse,
    RemediationApproveRequest,
    RemediationCancelRequest,
    RemediationDetailResponse,
    RemediationExecuteRequest,
    RemediationExecutionMode,
    RemediationProposeRequest,
    RemediationReconcileRequest,
    RemediationRejectRequest,
    RemediationStatus,
)
from app.services.incident_service import IncidentNotFoundError, ProjectIsolationError
from app.services.remediation.adapter import (
    RealMicroserviceExecutionAdapter,
    SimulatedExecutionAdapter,
)
from app.services.remediation.exceptions import (
    ActionNotAllowlistedError,
    DuplicateExecutionError,
    InvalidRemediationStateError,
    ParameterValidationError,
    RemediationExecutionError,
    RemediationNotFoundError,
    RemediationTimeoutError,
)

logger = logging.getLogger(__name__)

# Execution claim lease duration: 120 seconds
EXECUTION_LEASE_DURATION_SECONDS = 120


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensures datetime is timezone-aware UTC, even across SQLite naive storage."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class RemediationService:
    """Orchestrates human approvals, state machine transitions, and safe execution adapters."""

    def __init__(self, db: Session):
        self.db = db

    def _resolve_incident(
        self,
        incident_id_or_number: str,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> Incident:
        """Finds incident by UUID or incident_number and enforces project ownership."""
        if not project_id:
            raise ProjectIsolationError("Project context is mandatory for tenant isolation.")
        if not actor.can_access_project(project_id):
            raise ProjectIsolationError(f"Actor '{actor.email}' is not authorized to access project '{project_id}'.")

        query = self.db.query(Incident)
        try:
            val_uuid = UUID(incident_id_or_number)
            incident = query.filter(Incident.id == val_uuid).first()
        except (ValueError, TypeError):
            incident = query.filter(Incident.incident_number == incident_id_or_number).first()

        if not incident:
            raise IncidentNotFoundError(f"Incident '{incident_id_or_number}' not found.")

        # Anti-IDOR: Check that the incident actually belongs to the caller's project
        if incident.project_id != project_id:
            raise ProjectIsolationError(
                f"Incident '{incident_id_or_number}' does not belong to project '{project_id}'."
            )

        return incident

    def _get_recommendation_and_incident(
        self,
        remediation_id: UUID,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> tuple[Recommendation, Incident]:
        """Resolves Recommendation and associated Incident while strictly enforcing tenant isolation."""
        if not project_id:
            raise ProjectIsolationError("Project context is mandatory for tenant isolation.")
        if not actor.can_access_project(project_id):
            raise ProjectIsolationError(f"Actor '{actor.email}' is not authorized to access project '{project_id}'.")

        rec = self.db.query(Recommendation).filter(Recommendation.id == remediation_id).first()
        if not rec:
            raise RemediationNotFoundError(f"Remediation '{remediation_id}' not found.")

        # Find linked incident via direct FK or investigation
        incident = None
        if rec.incident_id:
            incident = self.db.query(Incident).filter(Incident.id == rec.incident_id).first()

        if not incident and rec.investigation_id:
            inv = self.db.query(Investigation).filter(Investigation.id == rec.investigation_id).first()
            if inv:
                if inv.incident_id:
                    incident = self.db.query(Incident).filter(Incident.id == inv.incident_id).first()
                elif inv.correlation_group_id:
                    incident = self.db.query(Incident).filter(
                        Incident.correlation_group_id == inv.correlation_group_id
                    ).first()

        if not incident:
            raise IncidentNotFoundError(f"Associated incident for remediation '{remediation_id}' could not be resolved.")

        # Strict project boundary verification
        if incident.project_id != project_id:
            raise ProjectIsolationError(
                f"Remediation '{remediation_id}' belongs to project '{incident.project_id}', not '{project_id}'."
            )

        # Backfill direct relationship if not already persisted
        if not rec.project_id or not rec.incident_id:
            rec.project_id = incident.project_id
            rec.incident_id = incident.id
            self.db.commit()

        return rec, incident

    def _to_detail_response(
        self,
        rec: Recommendation,
        incident: Optional[Incident] = None,
    ) -> RemediationDetailResponse:
        """Converts ORM Recommendation to RemediationDetailResponse DTO."""
        dto = RemediationDetailResponse.model_validate(rec)
        if incident:
            dto.incident_id = incident.id
            dto.incident_number = incident.incident_number
            dto.project_id = incident.project_id
        return dto

    def _record_audit_event(
        self,
        incident: Incident,
        event_type: str,
        actor: AuthenticatedActor,
        title: str,
        description: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> IncidentEvent:
        """Appends an immutable audit event to the incident's timeline attributed to the authenticated actor."""
        audit_payload = payload or {}
        audit_payload.update({
            "actor_id": actor.actor_id,
            "actor_email": actor.email,
            "actor_role": actor.role.value,
        })
        event = IncidentEvent(
            incident_id=incident.id,
            timestamp=datetime.now(timezone.utc),
            title=title,
            event_type=event_type,
            source=f"{actor.name} ({actor.role.value})",
            description=description,
            payload=audit_payload,
        )
        self.db.add(event)
        return event

    def get_remediation(
        self,
        remediation_id: UUID,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> RemediationDetailResponse:
        rec, incident = self._get_recommendation_and_incident(remediation_id, project_id, actor)
        return self._to_detail_response(rec, incident)

    def list_remediations_for_incident(
        self,
        incident_id_or_number: str,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> List[RemediationDetailResponse]:
        incident = self._resolve_incident(incident_id_or_number, project_id, actor)

        inv_ids = []
        direct_invs = self.db.query(Investigation.id).filter(Investigation.incident_id == incident.id).all()
        inv_ids.extend([i[0] for i in direct_invs])

        if incident.correlation_group_id:
            group_invs = self.db.query(Investigation.id).filter(
                Investigation.correlation_group_id == incident.correlation_group_id
            ).all()
            inv_ids.extend([i[0] for i in group_invs])

        query = self.db.query(Recommendation)
        if inv_ids:
            query = query.filter(
                (Recommendation.incident_id == incident.id) | (Recommendation.investigation_id.in_(inv_ids))
            )
        else:
            query = query.filter(Recommendation.incident_id == incident.id)

        recs = query.order_by(Recommendation.created_at.desc()).all()
        return [self._to_detail_response(r, incident) for r in recs]

    def propose_remediation(
        self,
        incident_id_or_number: str,
        req: RemediationProposeRequest,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> RemediationDetailResponse:
        if not actor.can_propose_remediation():
            raise InvalidRemediationStateError(f"Role '{actor.role.value}' is not authorized to propose remediations.")

        incident = self._resolve_incident(incident_id_or_number, project_id, actor)

        # Find or create investigation container
        inv = (
            self.db.query(Investigation)
            .filter(Investigation.incident_id == incident.id)
            .order_by(Investigation.created_at.desc())
            .first()
        )
        if not inv and incident.correlation_group_id:
            inv = (
                self.db.query(Investigation)
                .filter(Investigation.correlation_group_id == incident.correlation_group_id)
                .order_by(Investigation.created_at.desc())
                .first()
            )

        if not inv:
            inv = Investigation(
                incident_id=incident.id,
                correlation_group_id=incident.correlation_group_id,
                provider="operator-console",
                model_name="human-operator",
                status="COMPLETED",
                agent_name="Incident Remediation Command",
                summary="Manual remediation plan created by operator",
                is_demo=False,
            )
            self.db.add(inv)
            self.db.flush()

        rec = Recommendation(
            investigation_id=inv.id,
            incident_id=incident.id,
            project_id=incident.project_id,
            title=req.title,
            action_type=req.action_type,
            action_name=req.action_name.value,
            target_service=req.target_service,
            description=req.description,
            risk_level=req.risk_level.value,
            status=RemediationStatus.PROPOSED.value,
            is_dry_run_safe=True,
            requires_human_approval=True,
            action_parameters=req.action_parameters,
            preconditions=req.preconditions,
            rollback_procedure=req.rollback_procedure,
            expected_result=req.expected_result,
            verification_steps=req.verification_steps,
            is_demo=False,
        )
        self.db.add(rec)
        self.db.flush()

        self._record_audit_event(
            incident=incident,
            event_type="action",
            actor=actor,
            title=f"Remediation Proposed: {req.title}",
            description=f"Action '{req.action_name.value}' proposed by {actor.name} for service '{req.target_service}'.",
            payload={
                "recommendation_id": str(rec.id),
                "action_name": req.action_name.value,
                "target_service": req.target_service,
                "risk_level": req.risk_level.value,
            },
        )
        self.db.commit()
        self.db.refresh(rec)
        return self._to_detail_response(rec, incident)

    def approve_remediation(
        self,
        remediation_id: UUID,
        req: RemediationApproveRequest,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> RemediationDetailResponse:
        if not actor.can_approve_remediation():
            raise InvalidRemediationStateError(f"Role '{actor.role.value}' is not authorized to approve remediations.")

        rec, incident = self._get_recommendation_and_incident(remediation_id, project_id, actor)

        if rec.status == RemediationStatus.APPROVED.value:
            # Idempotent re-approval
            return self._to_detail_response(rec, incident)

        if rec.status not in (
            RemediationStatus.PROPOSED.value,
            RemediationStatus.FAILED.value,
            RemediationStatus.OUTCOME_UNKNOWN.value,
        ):
            raise InvalidRemediationStateError(
                f"Cannot approve remediation in state '{rec.status}'. Only 'PROPOSED', 'FAILED', or 'OUTCOME_UNKNOWN' can be approved."
            )

        now = datetime.now(timezone.utc)
        rec.status = RemediationStatus.APPROVED.value
        rec.approved_by = actor.name  # SEC-01: Derived strictly from authenticated principal
        rec.approved_at = now
        rec.approval_notes = req.approval_notes

        self._record_audit_event(
            incident=incident,
            event_type="human",
            actor=actor,
            title=f"Remediation Approved: {rec.title}",
            description=f"Remediation approved by {actor.name}. Justification: {req.approval_notes or 'None'}",
            payload={
                "recommendation_id": str(rec.id),
                "action_name": rec.action_name,
                "approved_at": now.isoformat(),
            },
        )
        self.db.commit()
        self.db.refresh(rec)
        return self._to_detail_response(rec, incident)

    def reject_remediation(
        self,
        remediation_id: UUID,
        req: RemediationRejectRequest,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> RemediationDetailResponse:
        if not actor.can_reject_remediation():
            raise InvalidRemediationStateError(f"Role '{actor.role.value}' is not authorized to reject remediations.")

        rec, incident = self._get_recommendation_and_incident(remediation_id, project_id, actor)

        if rec.status == RemediationStatus.REJECTED.value:
            return self._to_detail_response(rec, incident)

        if rec.status not in (RemediationStatus.PROPOSED.value, RemediationStatus.APPROVED.value):
            raise InvalidRemediationStateError(
                f"Cannot reject remediation in state '{rec.status}'. Only 'PROPOSED' or 'APPROVED' can be rejected."
            )

        now = datetime.now(timezone.utc)
        rec.status = RemediationStatus.REJECTED.value
        rec.rejected_by = actor.name  # SEC-01
        rec.rejected_at = now
        rec.rejection_reason = req.rejection_reason

        self._record_audit_event(
            incident=incident,
            event_type="human",
            actor=actor,
            title=f"Remediation Rejected: {rec.title}",
            description=f"Remediation rejected by {actor.name}. Reason: {req.rejection_reason}",
            payload={
                "recommendation_id": str(rec.id),
                "action_name": rec.action_name,
                "reason": req.rejection_reason,
                "rejected_at": now.isoformat(),
            },
        )
        self.db.commit()
        self.db.refresh(rec)
        return self._to_detail_response(rec, incident)

    def cancel_remediation(
        self,
        remediation_id: UUID,
        req: RemediationCancelRequest,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> RemediationDetailResponse:
        if not actor.can_cancel_remediation():
            raise InvalidRemediationStateError(f"Role '{actor.role.value}' is not authorized to cancel remediations.")

        rec, incident = self._get_recommendation_and_incident(remediation_id, project_id, actor)

        if rec.status == RemediationStatus.CANCELLED.value:
            return self._to_detail_response(rec, incident)

        if rec.status in (RemediationStatus.EXECUTING.value, RemediationStatus.EXECUTED.value):
            raise InvalidRemediationStateError(f"Cannot cancel remediation in state '{rec.status}'.")

        rec.status = RemediationStatus.CANCELLED.value
        self._record_audit_event(
            incident=incident,
            event_type="human",
            actor=actor,
            title=f"Remediation Cancelled: {rec.title}",
            description=f"Remediation cancelled by {actor.name}. Reason: {req.cancellation_reason or 'None'}",
            payload={
                "recommendation_id": str(rec.id),
            },
        )
        self.db.commit()
        self.db.refresh(rec)
        return self._to_detail_response(rec, incident)

    def execute_remediation(
        self,
        remediation_id: UUID,
        req: RemediationExecuteRequest,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> RemediationDetailResponse:
        """Executes an approved remediation with atomic claim locking, strict failure preservation, and no silent simulation fallback."""
        if not actor.can_execute_remediation():
            raise InvalidRemediationStateError(f"Role '{actor.role.value}' is not authorized to execute remediations.")

        rec, incident = self._get_recommendation_and_incident(remediation_id, project_id, actor)

        # 1. State machine validation
        if rec.status == RemediationStatus.PROPOSED.value:
            raise InvalidRemediationStateError("Remediation requires explicit human approval before execution. Current status is 'PROPOSED'.")
        if rec.status == RemediationStatus.REJECTED.value:
            raise InvalidRemediationStateError("Cannot execute a REJECTED remediation.")
        if rec.status == RemediationStatus.CANCELLED.value:
            raise InvalidRemediationStateError("Cannot execute a CANCELLED remediation.")

        # 2. Idempotency check for already completed execution
        if rec.status == RemediationStatus.EXECUTED.value:
            if req.idempotency_key and rec.execution_idempotency_key == req.idempotency_key:
                logger.info("Remediation %s already EXECUTED with matching idempotency key. Returning cached response.", rec.id)
                return self._to_detail_response(rec, incident)
            return self._to_detail_response(rec, incident)

        # 3. Allowlist validation
        action_name = rec.action_name or AllowlistedAction.RESET_SERVICE_FAULTS.value
        allowlisted_values = [a.value for a in AllowlistedAction]
        if action_name not in allowlisted_values:
            raise ActionNotAllowlistedError(f"Action '{action_name}' is not in the approved remediation allowlist: {allowlisted_values}")

        target_service = rec.target_service or "inventory-service"
        parameters = rec.action_parameters or {}

        # 4. Atomic execution claim (REL-01)
        now = datetime.now(timezone.utc)
        attempt_id = f"attempt_{uuid4().hex[:12]}"
        lease_expires = now + timedelta(seconds=EXECUTION_LEASE_DURATION_SECONDS)
        idempotency_token = req.idempotency_key or f"idem_{uuid4().hex[:16]}"

        stmt = (
            update(Recommendation)
            .where(
                Recommendation.id == remediation_id,
                Recommendation.status == RemediationStatus.APPROVED.value,
            )
            .values(
                status=RemediationStatus.EXECUTING.value,
                executed_by=actor.name,  # SEC-01: Derived strictly from authenticated principal
                execution_started_at=now,
                execution_lease_expires_at=lease_expires,
                execution_attempt_id=attempt_id,
                execution_idempotency_key=idempotency_token,
            )
        )
        claim_result = self.db.execute(stmt)
        self.db.commit()

        if claim_result.rowcount == 0:
            # Re-read to diagnose exact conflict reason
            self.db.refresh(rec)
            if rec.status == RemediationStatus.EXECUTING.value:
                raise DuplicateExecutionError("Remediation action is currently actively executing under another worker.")
            if rec.status == RemediationStatus.EXECUTED.value:
                return self._to_detail_response(rec, incident)
            raise InvalidRemediationStateError(f"Cannot execute remediation in state '{rec.status}'. Must be in 'APPROVED' state.")

        self.db.refresh(rec)

        self._record_audit_event(
            incident=incident,
            event_type="action",
            actor=actor,
            title=f"Remediation Execution Started: {rec.title}",
            description=f"Operator {actor.name} initiated execution of action '{action_name}' on '{target_service}' (Attempt: {attempt_id}).",
            payload={
                "recommendation_id": str(rec.id),
                "action_name": action_name,
                "target_service": target_service,
                "attempt_id": attempt_id,
            },
        )
        self.db.commit()

        # 5. Determine execution mode explicitly (REL-02)
        # Real execution is performed ONLY when real adapter can handle it AND simulated mode is not explicitly forced
        target_mode = RemediationExecutionMode.REAL
        if req.execution_mode == RemediationExecutionMode.SIMULATED or not RealMicroserviceExecutionAdapter.can_handle(action_name, target_service):
            target_mode = RemediationExecutionMode.SIMULATED

        # 6. Dispatch execution to adapter
        exec_timestamp = datetime.now(timezone.utc)
        try:
            if target_mode == RemediationExecutionMode.REAL:
                result = RealMicroserviceExecutionAdapter.execute(
                    action_name=action_name,
                    target_service=target_service,
                    parameters=parameters,
                )
            else:
                result = SimulatedExecutionAdapter.execute(
                    action_name=action_name,
                    target_service=target_service,
                    parameters=parameters,
                )

            # 7. Record Success
            rec.status = RemediationStatus.EXECUTED.value
            rec.executed_at = exec_timestamp
            rec.execution_mode = result.get("execution_mode", target_mode.value)
            rec.execution_result_json = result
            rec.execution_error = None

            self._record_audit_event(
                incident=incident,
                event_type="action",
                actor=actor,
                title=f"Remediation Executed: {rec.title}",
                description=f"Action '{action_name}' successfully executed on {target_service} ({rec.execution_mode}).",
                payload=result,
            )
            self.db.commit()
            self.db.refresh(rec)
            return self._to_detail_response(rec, incident)

        except RemediationTimeoutError as timeout_err:
            # REL-02 & REL-03: Network timeout after request dispatched -> Treat as uncertain outcome OUTCOME_UNKNOWN
            logger.error("Execution timed out calling target service %s: %s", target_service, timeout_err)
            rec.status = RemediationStatus.OUTCOME_UNKNOWN.value
            rec.executed_at = exec_timestamp
            rec.execution_mode = target_mode.value
            rec.execution_error = f"Timeout after dispatching external request: {str(timeout_err)}"

            self._record_audit_event(
                incident=incident,
                event_type="action",
                actor=actor,
                title=f"Remediation Execution Outcome Uncertain: {rec.title}",
                description=f"Action '{action_name}' timed out after dispatch. State set to OUTCOME_UNKNOWN. Do not re-execute automatically.",
                payload={"error": str(timeout_err), "attempt_id": attempt_id},
            )
            self.db.commit()
            self.db.refresh(rec)
            raise

        except Exception as exc:
            # REL-02 & REL-03: Real execution failed -> Persist FAILED and persist failure audit event. NEVER fall back to simulated success!
            logger.error("Execution failed for remediation %s: %s", rec.id, exc)
            rec.status = RemediationStatus.FAILED.value
            rec.executed_at = exec_timestamp
            rec.execution_mode = target_mode.value
            rec.execution_error = str(exc)

            self._record_audit_event(
                incident=incident,
                event_type="action",
                actor=actor,
                title=f"Remediation Failed: {rec.title}",
                description=f"Execution of action '{action_name}' on '{target_service}' failed: {str(exc)}",
                payload={"error": str(exc), "attempt_id": attempt_id},
            )
            self.db.commit()
            self.db.refresh(rec)

            if isinstance(exc, (ActionNotAllowlistedError, ParameterValidationError, RemediationExecutionError)):
                raise
            raise RemediationExecutionError(f"Remediation execution failed: {str(exc)}") from exc

    def reconcile_stuck_execution(
        self,
        remediation_id: UUID,
        req: RemediationReconcileRequest,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> RemediationDetailResponse:
        """REL-04: Reconciles an abandoned or crashed remediation in EXECUTING state whose lease expired."""
        if not actor.can_execute_remediation():
            raise InvalidRemediationStateError(f"Role '{actor.role.value}' is not authorized to reconcile remediations.")

        rec, incident = self._get_recommendation_and_incident(remediation_id, project_id, actor)

        if rec.status != RemediationStatus.EXECUTING.value:
            raise InvalidRemediationStateError(
                f"Remediation is in status '{rec.status}'. Only 'EXECUTING' actions can be reconciled."
            )

        now = datetime.now(timezone.utc)
        lease_expires = ensure_utc(rec.execution_lease_expires_at)
        if lease_expires and now < lease_expires:
            remaining = int((lease_expires - now).total_seconds())
            raise InvalidRemediationStateError(
                f"Execution lease is still active ({remaining}s remaining). Cannot reconcile until lease expires."
            )

        target_status = req.force_outcome or RemediationStatus.OUTCOME_UNKNOWN
        if target_status not in (RemediationStatus.OUTCOME_UNKNOWN, RemediationStatus.FAILED):
            target_status = RemediationStatus.OUTCOME_UNKNOWN

        rec.status = target_status.value
        rec.execution_error = req.reconciliation_notes or "Reconciled from abandoned EXECUTING state following execution lease expiration."

        self._record_audit_event(
            incident=incident,
            event_type="human",
            actor=actor,
            title=f"Remediation Lease Reconciled: {rec.title}",
            description=f"Stuck execution reconciled to '{target_status.value}' by {actor.name}. Reason: {rec.execution_error}",
            payload={
                "previous_status": "EXECUTING",
                "reconciled_status": target_status.value,
                "notes": req.reconciliation_notes,
            },
        )
        self.db.commit()
        self.db.refresh(rec)
        return self._to_detail_response(rec, incident)
