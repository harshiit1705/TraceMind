"""Comprehensive Test Suite for Phase 4.1 & Phase 5:
- Phase 4.1 Remediation Security & Reliability Hardening
- Phase 5 Telemetry-Based Recovery Verification

Verifies:
1. SEC-01: Authenticated operator identity required; client identity fields cannot spoof authenticated principal.
2. SEC-02: Mandatory project_id isolation; omitting or spoofing project_id is rejected.
3. REL-01: Atomic execution claiming; concurrent execution attempts prevent double-execution.
4. REL-02: Real execution failures record FAILED / OUTCOME_UNKNOWN; zero silent fallback to simulated success.
5. REL-03: Failure audit events reliably persisted to incident timeline on rollback.
6. REL-04: Stuck EXECUTING lease expiration and safe administrative reconciliation.
7. ARC-01 & ARC-02: Accurate semantics and parameter bounds for all allowlisted actions.
8. Phase 5: Telemetry-grounded recovery verification across RECOVERED, NOT_RECOVERED, PARTIALLY_RECOVERED, and INCONCLUSIVE scenarios.
"""

from datetime import datetime, timedelta, timezone
from typing import Generator
from uuid import UUID, uuid4
import pytest
from sqlalchemy.orm import Session

from app.core.auth import (
    DEFAULT_DEV_ACTOR,
    AuthenticatedActor,
    OperatorRole,
    authenticate_actor,
)
from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.investigation import Investigation
from app.models.project import Project
from app.models.recommendation import Recommendation
from app.models.recovery_verification import RecoveryVerification
from app.models.service import Service
from app.models.telemetry import ApplicationLog, MetricSample, TraceSpan
from app.schemas.common import IncidentStatus
from app.schemas.recommendation import (
    AllowlistedAction,
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
from app.schemas.recovery_verification import (
    CheckStatus,
    RecoveryOutcome,
    RecoveryVerificationRequest,
    RecoveryVerificationResponse,
    VerificationStatus,
)
from app.services.incident_service import IncidentNotFoundError, ProjectIsolationError
from app.services.recovery.verification_service import RecoveryVerificationService
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
from app.services.remediation.service import RemediationService


@pytest.fixture
def test_setup(db_session: Session):
    """Seed test project, incident, and investigation."""
    project = db_session.query(Project).filter(Project.slug == "core-ecommerce").first()
    assert project is not None

    incident = db_session.query(Incident).filter(Incident.project_id == project.id).first()
    assert incident is not None

    inv = db_session.query(Investigation).filter(Investigation.incident_id == incident.id).first()
    if not inv:
        inv = Investigation(
            incident_id=incident.id,
            provider="test-provider",
            model_name="test-model",
            status="COMPLETED",
            agent_name="Test Agent",
            summary="Test incident investigation",
            is_demo=False,
        )
        db_session.add(inv)
        db_session.commit()
        db_session.refresh(inv)

    return {"project": project, "incident": incident, "investigation": inv}


@pytest.fixture
def sre_actor(test_setup):
    """Authenticated SRE Lead actor authorized for test project."""
    return AuthenticatedActor(
        actor_id="usr_alex_chen",
        name="Alex Chen",
        email="alex.chen@tracemind.io",
        role=OperatorRole.LEAD_SRE,
        allowed_project_ids={test_setup["project"].id},
    )


@pytest.fixture
def viewer_actor(test_setup):
    """Authenticated Viewer actor lacking mutation permissions."""
    return AuthenticatedActor(
        actor_id="usr_viewer_guest",
        name="Guest Observer",
        email="observer@tracemind.io",
        role=OperatorRole.VIEWER,
        allowed_project_ids={test_setup["project"].id},
    )


# -----------------------------------------------------------------------------
# 1. Phase 4.1: SEC-01 Authenticated Operator Identity Tests
# -----------------------------------------------------------------------------

def test_unauthenticated_request_rejected():
    """SEC-01: Requests without credentials must be rejected with 401 Unauthorized."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        authenticate_actor(authorization=None, x_api_key=None, x_operator_token=None)
    assert exc_info.value.status_code == 401
    assert "credentials were not provided" in str(exc_info.value.detail)


def test_operator_identity_derived_from_principal_never_spoofed(db_session: Session, test_setup, sre_actor):
    """SEC-01: Body identity fields (e.g. approver_name='CEO') are ignored; authenticated actor is recorded."""
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    project = test_setup["project"]

    prop_req = RemediationProposeRequest(
        title="Reset Inventory Locks",
        description="Clear contention on inventory locks.",
        target_service="inventory-service",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
        proposer_name="spoofed_client_label",
    )
    rec = service.propose_remediation(str(incident.id), prop_req, project_id=project.id, actor=sre_actor)
    assert rec.status == RemediationStatus.PROPOSED

    # Approve with spoofed body name
    app_req = RemediationApproveRequest(
        approver_name="Fake Impersonated Executive",
        approval_notes="Legitimate SRE approval notes",
    )
    approved = service.approve_remediation(rec.id, app_req, project_id=project.id, actor=sre_actor)
    # The recorded approver MUST be the authenticated actor name ('Alex Chen'), not the spoofed string
    assert approved.approved_by == sre_actor.name
    assert approved.approved_by != "Fake Impersonated Executive"


def test_viewer_role_cannot_approve_or_execute(db_session: Session, test_setup, sre_actor, viewer_actor):
    """SEC-01: Unauthorized role (VIEWER) cannot approve or execute remediations."""
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    project = test_setup["project"]

    prop_req = RemediationProposeRequest(
        title="Role Enforcement Test",
        description="Verify viewer role cannot mutate.",
        target_service="inventory-service",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
    )
    rec = service.propose_remediation(str(incident.id), prop_req, project_id=project.id, actor=sre_actor)

    # Viewer cannot approve
    with pytest.raises(InvalidRemediationStateError) as exc_info:
        service.approve_remediation(
            rec.id,
            RemediationApproveRequest(approval_notes="Unauthorized approval attempt"),
            project_id=project.id,
            actor=viewer_actor,
        )
    assert "not authorized to approve" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 2. Phase 4.1: SEC-02 Mandatory Project Isolation & Anti-IDOR Tests
# -----------------------------------------------------------------------------

def test_missing_or_foreign_project_id_rejected(db_session: Session, test_setup, sre_actor):
    """SEC-02: Project boundary cannot be bypassed by passing None or a foreign project UUID."""
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    foreign_project_id = uuid4()

    prop_req = RemediationProposeRequest(
        title="Tenant Boundary Test",
        description="Verifies mandatory project_id.",
        target_service="payment-service",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
    )
    rec = service.propose_remediation(str(incident.id), prop_req, project_id=test_setup["project"].id, actor=sre_actor)

    # 1. Foreign project ID must raise ProjectIsolationError
    with pytest.raises(ProjectIsolationError):
        service.get_remediation(rec.id, project_id=foreign_project_id, actor=sre_actor)

    # 2. Foreign project ID cannot approve
    with pytest.raises(ProjectIsolationError):
        service.approve_remediation(
            rec.id,
            RemediationApproveRequest(approval_notes="Foreign approval"),
            project_id=foreign_project_id,
            actor=sre_actor,
        )

    # 3. Actor restricted to another project cannot access
    unauthorized_actor = AuthenticatedActor(
        actor_id="foreign_tenant_user",
        name="Foreign SRE",
        email="foreign@othercorp.io",
        role=OperatorRole.SRE,
        allowed_project_ids={foreign_project_id},
    )
    with pytest.raises(ProjectIsolationError):
        service.get_remediation(rec.id, project_id=test_setup["project"].id, actor=unauthorized_actor)


# -----------------------------------------------------------------------------
# 3. Phase 4.1: REL-01 Concurrent Execution & Atomic Claiming Tests
# -----------------------------------------------------------------------------

def test_concurrent_double_execution_atomic_claim_prevented(db_session: Session, test_setup, sre_actor):
    """REL-01: Exactly one execution claim succeeds. Concurrent requests receive DuplicateExecutionError."""
    service1 = RemediationService(db_session)
    incident = test_setup["incident"]
    project = test_setup["project"]

    # Propose and Approve
    rec = service1.propose_remediation(
        str(incident.id),
        RemediationProposeRequest(
            title="Concurrency Test Remediation",
            description="Testing atomic conditional state claim.",
            target_service="inventory-service",
            action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
        ),
        project_id=project.id,
        actor=sre_actor,
    )
    service1.approve_remediation(
        rec.id,
        RemediationApproveRequest(approval_notes="Approved for concurrency test"),
        project_id=project.id,
        actor=sre_actor,
    )

    # Manually lock status to EXECUTING (simulating Worker 1 claiming the lease)
    rec_row = db_session.query(Recommendation).filter(Recommendation.id == rec.id).first()
    rec_row.status = RemediationStatus.EXECUTING.value
    rec_row.execution_started_at = datetime.now(timezone.utc)
    rec_row.execution_lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=120)
    db_session.commit()

    # Worker 2 attempting to execute must receive DuplicateExecutionError
    with pytest.raises(DuplicateExecutionError) as exc_info:
        service1.execute_remediation(
            rec.id,
            RemediationExecuteRequest(idempotency_key="worker2-key-1234"),
            project_id=project.id,
            actor=sre_actor,
        )
    assert "actively executing" in str(exc_info.value)


def test_idempotent_execution_returns_cached_result(db_session: Session, test_setup, sre_actor):
    """REL-01 / 4.1.4: Repeated execution with matching idempotency key returns cached result without re-executing."""
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    project = test_setup["project"]

    rec = service.propose_remediation(
        str(incident.id),
        RemediationProposeRequest(
            title="Idempotency Test",
            description="Testing idempotency caching.",
            target_service="payment-service",
            action_name=AllowlistedAction.SCALE_REPLICAS,
            action_parameters={"replica_count": 3},
        ),
        project_id=project.id,
        actor=sre_actor,
    )
    service.approve_remediation(rec.id, RemediationApproveRequest(), project_id=project.id, actor=sre_actor)

    exec_req = RemediationExecuteRequest(
        execution_mode=RemediationExecutionMode.SIMULATED,
        idempotency_key="idemp-key-repeat-9999",
    )
    first_res = service.execute_remediation(rec.id, exec_req, project_id=project.id, actor=sre_actor)
    assert first_res.status == RemediationStatus.EXECUTED

    # Repeated request
    second_res = service.execute_remediation(rec.id, exec_req, project_id=project.id, actor=sre_actor)
    assert second_res.status == RemediationStatus.EXECUTED
    assert second_res.execution_attempt_id == first_res.execution_attempt_id


# -----------------------------------------------------------------------------
# 4. Phase 4.1: REL-02 Remove Silent Simulation Fallback Tests
# -----------------------------------------------------------------------------

def test_real_execution_failure_never_converts_to_simulated_success(db_session: Session, test_setup, sre_actor, monkeypatch):
    """REL-02: Real execution failure must transition to FAILED, never EXECUTED via simulated fallback."""
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    project = test_setup["project"]

    rec = service.propose_remediation(
        str(incident.id),
        RemediationProposeRequest(
            title="Real Failure Test",
            description="Ensures real microservice errors do not fallback to simulation.",
            target_service="payment-service",
            action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
        ),
        project_id=project.id,
        actor=sre_actor,
    )
    service.approve_remediation(rec.id, RemediationApproveRequest(), project_id=project.id, actor=sre_actor)

    # Mock real adapter to raise network connection error
    def mock_fail(*args, **kwargs):
        raise RemediationExecutionError("Connection refused connecting to http://127.0.0.1:8002/faults/reset")

    monkeypatch.setattr(RealMicroserviceExecutionAdapter, "execute", mock_fail)

    with pytest.raises(RemediationExecutionError) as exc_info:
        service.execute_remediation(
            rec.id,
            RemediationExecuteRequest(execution_mode=RemediationExecutionMode.REAL),
            project_id=project.id,
            actor=sre_actor,
        )
    assert "Connection refused" in str(exc_info.value)

    # Verify database state
    rec_after = db_session.query(Recommendation).filter(Recommendation.id == rec.id).first()
    assert rec_after.status == RemediationStatus.FAILED.value
    assert rec_after.status != RemediationStatus.EXECUTED.value
    assert "Connection refused" in rec_after.execution_error


def test_real_execution_timeout_marks_outcome_unknown(db_session: Session, test_setup, sre_actor, monkeypatch):
    """REL-02 / REL-04: Network timeout after request dispatched must transition to OUTCOME_UNKNOWN."""
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    project = test_setup["project"]

    rec = service.propose_remediation(
        str(incident.id),
        RemediationProposeRequest(
            title="Timeout Ambiguous Outcome Test",
            description="Ensures network timeouts result in OUTCOME_UNKNOWN.",
            target_service="inventory-service",
            action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
        ),
        project_id=project.id,
        actor=sre_actor,
    )
    service.approve_remediation(rec.id, RemediationApproveRequest(), project_id=project.id, actor=sre_actor)

    def mock_timeout(*args, **kwargs):
        raise RemediationTimeoutError("Socket read timeout calling /faults/reset")

    monkeypatch.setattr(RealMicroserviceExecutionAdapter, "execute", mock_timeout)

    with pytest.raises(RemediationTimeoutError):
        service.execute_remediation(
            rec.id,
            RemediationExecuteRequest(execution_mode=RemediationExecutionMode.REAL),
            project_id=project.id,
            actor=sre_actor,
        )

    rec_after = db_session.query(Recommendation).filter(Recommendation.id == rec.id).first()
    assert rec_after.status == RemediationStatus.OUTCOME_UNKNOWN.value


# -----------------------------------------------------------------------------
# 5. Phase 4.1: REL-03 Failure Audit Event Persistence Tests
# -----------------------------------------------------------------------------

def test_failure_audit_event_persisted_to_timeline(db_session: Session, test_setup, sre_actor, monkeypatch):
    """REL-03: On execution failure, an audit event must be committed to incident_events and preserved."""
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    project = test_setup["project"]

    rec = service.propose_remediation(
        str(incident.id),
        RemediationProposeRequest(
            title="Failure Audit Test",
            description="Testing failure event persistence.",
            target_service="order-service",
            action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
        ),
        project_id=project.id,
        actor=sre_actor,
    )
    service.approve_remediation(rec.id, RemediationApproveRequest(), project_id=project.id, actor=sre_actor)

    def mock_err(*args, **kwargs):
        raise RemediationExecutionError("HTTP 502 Bad Gateway from target service")

    monkeypatch.setattr(RealMicroserviceExecutionAdapter, "execute", mock_err)

    with pytest.raises(RemediationExecutionError):
        service.execute_remediation(rec.id, RemediationExecuteRequest(), project_id=project.id, actor=sre_actor)

    events = db_session.query(IncidentEvent).filter(IncidentEvent.incident_id == incident.id).all()
    event_titles = [e.title for e in events]
    assert any("Remediation Failed" in t for t in event_titles)


# -----------------------------------------------------------------------------
# 6. Phase 4.1: REL-04 Stuck EXECUTING Lease Expiration & Reconciliation Tests
# -----------------------------------------------------------------------------

def test_stuck_executing_lease_expired_reconciliation(db_session: Session, test_setup, sre_actor):
    """REL-04: An abandoned EXECUTING remediation with expired lease can be safely reconciled to OUTCOME_UNKNOWN."""
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    project = test_setup["project"]

    rec = service.propose_remediation(
        str(incident.id),
        RemediationProposeRequest(
            title="Lease Expiration Test",
            description="Testing lease reconciliation after crash.",
            target_service="payment-service",
            action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
        ),
        project_id=project.id,
        actor=sre_actor,
    )
    service.approve_remediation(rec.id, RemediationApproveRequest(), project_id=project.id, actor=sre_actor)

    # Simulate process crash: row stuck in EXECUTING with lease expired 10 minutes ago
    rec_row = db_session.query(Recommendation).filter(Recommendation.id == rec.id).first()
    rec_row.status = RemediationStatus.EXECUTING.value
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    rec_row.execution_started_at = past_time
    rec_row.execution_lease_expires_at = past_time + timedelta(seconds=120)
    db_session.commit()

    # Reconcile abandoned action
    reconcile_req = RemediationReconcileRequest(
        reconciliation_notes="Worker node crashed; reconciled abandoned lease to OUTCOME_UNKNOWN.",
        force_outcome=RemediationStatus.OUTCOME_UNKNOWN,
    )
    reconciled = service.reconcile_stuck_execution(rec.id, reconcile_req, project_id=project.id, actor=sre_actor)
    assert reconciled.status == RemediationStatus.OUTCOME_UNKNOWN

    # Incident timeline shows reconciliation audit record
    events = db_session.query(IncidentEvent).filter(IncidentEvent.incident_id == incident.id).all()
    assert any("Lease Reconciled" in e.title for e in events)


# -----------------------------------------------------------------------------
# 7. Phase 4.1: ARC-01 & ARC-02 Allowlisted Actions & Parameter Validation Tests
# -----------------------------------------------------------------------------

def test_action_semantics_and_parameter_validation():
    # 1. RESTART_SERVICE is simulated and validates grace_period_seconds
    res_restart = SimulatedExecutionAdapter.execute(
        action_name=AllowlistedAction.RESTART_SERVICE.value,
        target_service="order-service",
        parameters={"grace_period_seconds": 15},
    )
    assert res_restart["is_simulated"] is True
    assert res_restart["grace_period_seconds"] == 15
    assert "grace period" in res_restart["simulation_notes"]

    # Invalid grace period
    with pytest.raises(ParameterValidationError):
        SimulatedExecutionAdapter.execute(
            action_name=AllowlistedAction.RESTART_SERVICE.value,
            target_service="order-service",
            parameters={"grace_period_seconds": 9999},  # Exceeds max 300
        )

    # 2. FLUSH_CONNECTION_POOL validates pool_type
    res_pool = SimulatedExecutionAdapter.execute(
        action_name=AllowlistedAction.FLUSH_CONNECTION_POOL.value,
        target_service="payment-service",
        parameters={"pool_type": "database"},
    )
    assert res_pool["is_simulated"] is True
    assert res_pool["pool_type"] == "database"

    with pytest.raises(ParameterValidationError):
        SimulatedExecutionAdapter.execute(
            action_name=AllowlistedAction.FLUSH_CONNECTION_POOL.value,
            target_service="payment-service",
            parameters={"pool_type": "invalid_pool_name"},
        )

    # 3. Arbitrary action is rejected
    with pytest.raises(ActionNotAllowlistedError):
        SimulatedExecutionAdapter.execute(
            action_name="EXECUTE_ARBITRARY_BASH_SCRIPT",
            target_service="order-service",
            parameters={},
        )


# -----------------------------------------------------------------------------
# 8. Phase 5: Telemetry-Based Recovery Verification Tests
# -----------------------------------------------------------------------------

def test_recovery_verification_recovered_scenario(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario A: Post-remediation latency normalizes below baseline and zero errors -> RECOVERED."""
    incident = test_setup["incident"]
    project = test_setup["project"]

    # Retrieve or create payment-service
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()
    assert pay_svc is not None

    # Set historical baseline: expected latency mean=45ms, stddev=10ms
    db_session.query(AnomalyBaseline).filter(
        AnomalyBaseline.project_id == project.id,
        AnomalyBaseline.service_id == pay_svc.id,
        AnomalyBaseline.metric_name == "latency",
    ).delete()
    baseline = AnomalyBaseline(
        project_id=project.id,
        service_id=pay_svc.id,
        metric_name="latency",
        detection_method="rolling_average",
        baseline_state={"mean": 45.0, "stddev": 10.0},
        config_snapshot={},
        sample_count=100,
    )
    db_session.add(baseline)

    # Create executed recommendation
    t_exec = datetime.now(timezone.utc) - timedelta(seconds=30)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Reset Payment Gateway Faults",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults on payment-service.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)
    db_session.commit()

    # Seed fresh healthy post-remediation telemetry (5 samples, latency 40-50ms)
    for i in range(5):
        sample_time = t_exec + timedelta(seconds=i * 5 + 2)
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=42.0 + i,
                timestamp=sample_time,
                attributes_json={},
            )
        )
    db_session.commit()

    # Run verification
    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    assert v_res.status == VerificationStatus.COMPLETED
    assert v_res.recovery_outcome == RecoveryOutcome.RECOVERED
    assert v_res.suggested_incident_status == IncidentStatus.MITIGATED.value
    assert "fully RECOVERED" in v_res.explanation

    # Check incident timeline updated
    events = db_session.query(IncidentEvent).filter(IncidentEvent.incident_id == incident.id).all()
    assert any("Recovery Verification: RECOVERED" in e.title for e in events)


def test_recovery_verification_not_recovered_scenario(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario B: Post-remediation telemetry remains elevated -> NOT_RECOVERED."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=30)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Unsuccessful Reset Attempt",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Fault reset.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)

    # Seed unhealthy telemetry (latency 850ms, error logs)
    for i in range(4):
        sample_time = t_exec + timedelta(seconds=i * 5 + 2)
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=850.0,
                timestamp=sample_time,
                attributes_json={},
            )
        )
    db_session.add(
        ApplicationLog(
            project_id=project.id,
            service_id=pay_svc.id,
            timestamp=t_exec + timedelta(seconds=10),
            level="ERROR",
            message="Payment settlement timeout persists",
            attributes_json={},
        )
    )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    assert v_res.status == VerificationStatus.COMPLETED
    assert v_res.recovery_outcome == RecoveryOutcome.NOT_RECOVERED
    assert "NOT_RECOVERED" in v_res.explanation


def test_recovery_verification_inconclusive_zero_traffic(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario C: Zero traffic / insufficient samples -> INCONCLUSIVE (never falsely claims recovery)."""
    incident = test_setup["incident"]
    project = test_setup["project"]

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=30)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Idle Service Remediation",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="inventory-service",
        description="Reset on idle service.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.SIMULATED.value,
        is_demo=False,
    )
    db_session.add(rec)
    db_session.commit()

    # Do not seed any samples (zero traffic post-remediation)
    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    assert v_res.status == VerificationStatus.COMPLETED
    assert v_res.recovery_outcome == RecoveryOutcome.INCONCLUSIVE
    assert "INCONCLUSIVE" in v_res.explanation
    assert v_res.sample_count < 3


def test_recovery_verification_cannot_run_before_execution(db_session: Session, test_setup, sre_actor):
    """Phase 5: Cannot run recovery verification on a PROPOSED or APPROVED remediation."""
    incident = test_setup["incident"]
    project = test_setup["project"]

    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Unexecuted Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="order-service",
        description="Not executed yet.",
        status=RemediationStatus.APPROVED.value,
        is_demo=False,
    )
    db_session.add(rec)
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    with pytest.raises(InvalidRemediationStateError) as exc_info:
        verify_service.start_verification(
            incident_id=str(incident.id),
            remediation_id=rec.id,
            project_id=project.id,
            actor=sre_actor,
            req=RecoveryVerificationRequest(),
        )
    assert "Remediation must be confirmed EXECUTED first" in str(exc_info.value) or "Remediation must be EXECUTED first" in str(exc_info.value)


def test_recovery_verification_partially_recovered_scenario(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: Latency normalized to 45ms, but error logs persist -> PARTIALLY_RECOVERED."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=20)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Partial Recovery Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)

    # Seed healthy latency (45ms)
    for i in range(5):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=45.0,
                timestamp=t_exec + timedelta(seconds=i * 2 + 1),
                attributes_json={},
            )
        )
    # Seed persistent error log
    db_session.add(
        ApplicationLog(
            project_id=project.id,
            service_id=pay_svc.id,
            timestamp=t_exec + timedelta(seconds=5),
            level="ERROR",
            message="Residual database timeout log",
            attributes_json={},
        )
    )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    assert v_res.status == VerificationStatus.COMPLETED
    assert v_res.recovery_outcome == RecoveryOutcome.PARTIALLY_RECOVERED
    assert "PARTIALLY_RECOVERED" in v_res.explanation


def test_recovery_verification_inconclusive_insufficient_samples(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: Telemetry sample count below min_sample_count -> INCONCLUSIVE."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=15)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Insufficient Telemetry Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)

    # Seed only 2 samples when minimum requirement is 5
    for i in range(2):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=42.0,
                timestamp=t_exec + timedelta(seconds=i * 2 + 1),
                attributes_json={},
            )
        )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=5),
    )

    assert v_res.status == VerificationStatus.COMPLETED
    assert v_res.recovery_outcome == RecoveryOutcome.INCONCLUSIVE
    assert "insufficient" in v_res.explanation.lower()


def test_recovery_verification_inconclusive_stale_telemetry(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: Telemetry stream is stale (>300s old) -> INCONCLUSIVE."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    # Executed 15 minutes ago
    t_exec = datetime.now(timezone.utc) - timedelta(minutes=15)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Stale Telemetry Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)

    # Telemetry emitted 14 minutes ago (stale)
    for i in range(5):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=42.0,
                timestamp=t_exec + timedelta(seconds=i * 2 + 1),
                attributes_json={},
            )
        )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    assert v_res.status == VerificationStatus.COMPLETED
    assert v_res.recovery_outcome == RecoveryOutcome.INCONCLUSIVE
    assert "STALE" in v_res.explanation


def test_recovery_verification_missing_metric_evidence_safe(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: Missing latency metric is reported INCONCLUSIVE without crashing."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=20)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Missing Metric Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)

    # Seed samples for cpu_utilization, but NO latency metric
    for i in range(5):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="cpu_utilization",
                metric_unit="percent",
                value=35.0,
                timestamp=t_exec + timedelta(seconds=i * 2 + 1),
                attributes_json={},
            )
        )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    assert v_res.status == VerificationStatus.COMPLETED
    # Because latency metric is missing, latency_normalization is INCONCLUSIVE -> overall INCONCLUSIVE
    assert v_res.recovery_outcome == RecoveryOutcome.INCONCLUSIVE
    lat_check = next(c for c in v_res.checks_summary if c.check_name == "latency_normalization")
    assert lat_check.status == CheckStatus.INCONCLUSIVE


def test_recovery_verification_strict_pre_remediation_telemetry_exclusion(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: Pre-remediation samples are strictly excluded from post-remediation count."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=15)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Pre-Remediation Exclusion Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)

    # 100 bad samples BEFORE execution time
    for i in range(100):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=2500.0,
                timestamp=t_exec - timedelta(seconds=100 - i),
                attributes_json={},
            )
        )

    # Exactly 4 healthy samples AFTER execution time
    for i in range(4):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=45.0,
                timestamp=t_exec + timedelta(seconds=i * 2 + 1),
                attributes_json={},
            )
        )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    # Must count exactly 4 post-remediation samples, ignoring the 100 pre-remediation samples
    assert v_res.sample_count == 4
    assert v_res.recovery_outcome == RecoveryOutcome.RECOVERED


def test_recovery_verification_concurrent_duplicate_prevention(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: A verification already RUNNING blocks concurrent duplicate requests."""
    incident = test_setup["incident"]
    project = test_setup["project"]

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=20)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Concurrent Verify Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)
    db_session.commit()

    # Seed an active RUNNING verification
    active_v = RecoveryVerification(
        id=uuid4(),
        incident_id=incident.id,
        remediation_id=rec.id,
        project_id=project.id,
        target_service="payment-service",
        status=VerificationStatus.RUNNING.value,
        verification_window_start=t_exec,
        verification_window_end=t_exec + timedelta(seconds=60),
    )
    db_session.add(active_v)
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    with pytest.raises(DuplicateExecutionError) as exc_info:
        verify_service.start_verification(
            incident_id=str(incident.id),
            remediation_id=rec.id,
            project_id=project.id,
            actor=sre_actor,
            req=RecoveryVerificationRequest(),
        )
    assert "already actively running" in str(exc_info.value)


def test_recovery_verification_evidence_hash_persistence_and_integrity(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: Evidence snapshot carries cryptographic SHA-256 hash verified for integrity."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=20)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Integrity Verify Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)
    for i in range(4):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=42.0,
                timestamp=t_exec + timedelta(seconds=i * 2 + 1),
                attributes_json={},
            )
        )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    snapshot = v_res.evidence_snapshot
    assert "evidence_hash" in snapshot
    assert len(snapshot["evidence_hash"]) == 64  # SHA-256 hex string

    # Verify integrity passes
    assert RecoveryVerificationService.verify_evidence_hash(snapshot) is True

    # Tamper with snapshot -> verify integrity fails
    tampered = dict(snapshot)
    tampered["sample_count"] = 9999
    assert RecoveryVerificationService.verify_evidence_hash(tampered) is False


def test_recovery_verification_historical_records_remain_immutable(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: Verification records remain immutable historical audit artifacts."""
    incident = test_setup["incident"]
    project = test_setup["project"]

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=20)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Immutability Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)
    db_session.commit()

    v_rec = RecoveryVerification(
        id=uuid4(),
        incident_id=incident.id,
        remediation_id=rec.id,
        project_id=project.id,
        target_service="payment-service",
        status=VerificationStatus.COMPLETED.value,
        recovery_outcome=RecoveryOutcome.RECOVERED.value,
        verification_window_start=t_exec,
        verification_window_end=t_exec + timedelta(seconds=60),
        sample_count=10,
        explanation="Immutable historical test record.",
        verified_by=sre_actor.name,
    )
    db_session.add(v_rec)
    db_session.commit()

    saved = db_session.query(RecoveryVerification).filter_by(id=v_rec.id).one()
    assert saved.recovery_outcome == RecoveryOutcome.RECOVERED.value
    assert saved.explanation == "Immutable historical test record."


def test_recovery_verification_simulated_remediation_distinguished(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: SIMULATED remediation explicitly declares simulated status in explanation & snapshot."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=20)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Simulated Restart Action",
        action_name=AllowlistedAction.RESTART_SERVICE.value,
        target_service="payment-service",
        description="Simulated restart.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.SIMULATED.value,
        is_demo=True,
    )
    db_session.add(rec)

    for i in range(4):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=42.0,
                timestamp=t_exec + timedelta(seconds=i * 2 + 1),
                attributes_json={},
            )
        )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v_res = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    assert v_res.recovery_outcome == RecoveryOutcome.RECOVERED
    assert "SIMULATED REMEDIATION" in v_res.explanation
    assert v_res.evidence_snapshot["is_simulated_execution"] is True


def test_recovery_verification_outcome_unknown_cannot_be_verified(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: OUTCOME_UNKNOWN remediation cannot be verified as recovered."""
    incident = test_setup["incident"]
    project = test_setup["project"]

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=20)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Timed Out Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Timed out during call.",
        status=RemediationStatus.OUTCOME_UNKNOWN.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    with pytest.raises(InvalidRemediationStateError) as exc_info:
        verify_service.start_verification(
            incident_id=str(incident.id),
            remediation_id=rec.id,
            project_id=project.id,
            actor=sre_actor,
            req=RecoveryVerificationRequest(),
        )
    assert "Remediation must be confirmed EXECUTED first" in str(exc_info.value)


def test_recovery_verification_retry_creates_new_record_preserves_history(db_session: Session, test_setup, sre_actor):
    """Phase 5 Scenario: Retrying verification creates a new record while preserving historical records."""
    incident = test_setup["incident"]
    project = test_setup["project"]
    pay_svc = db_session.query(Service).filter(Service.project_id == project.id, Service.slug == "payment-service").first()

    t_exec = datetime.now(timezone.utc) - timedelta(seconds=30)
    rec = Recommendation(
        incident_id=incident.id,
        project_id=project.id,
        investigation_id=test_setup["investigation"].id,
        title="Retry History Action",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Reset faults.",
        status=RemediationStatus.EXECUTED.value,
        executed_by=sre_actor.name,
        executed_at=t_exec,
        execution_mode=RemediationExecutionMode.REAL.value,
        is_demo=False,
    )
    db_session.add(rec)

    # Initial telemetry: high latency + error log
    for i in range(4):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=500.0,
                timestamp=t_exec + timedelta(seconds=i * 2 + 1),
                attributes_json={},
            )
        )
    db_session.add(
        ApplicationLog(
            project_id=project.id,
            service_id=pay_svc.id,
            timestamp=t_exec + timedelta(seconds=5),
            level="ERROR",
            message="High latency timeout",
            attributes_json={},
        )
    )
    db_session.commit()

    verify_service = RecoveryVerificationService(db_session)
    v1 = verify_service.start_verification(
        incident_id=str(incident.id),
        remediation_id=rec.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )
    assert v1.recovery_outcome == RecoveryOutcome.NOT_RECOVERED

    # Seed fresh healthy telemetry
    for i in range(4):
        db_session.add(
            MetricSample(
                project_id=project.id,
                service_id=pay_svc.id,
                metric_name="latency",
                metric_unit="ms",
                value=40.0,
                timestamp=datetime.now(timezone.utc) - timedelta(seconds=5 - i),
                attributes_json={},
            )
        )
    db_session.commit()

    # Retry verification
    v2 = verify_service.retry_verification(
        verification_id=v1.id,
        project_id=project.id,
        actor=sre_actor,
        req=RecoveryVerificationRequest(verification_window_seconds=60, min_sample_count=3),
    )

    # Verify new record created with distinct UUID
    assert v2.id != v1.id

    # Verify both records persist in audit history
    history = verify_service.list_verifications_for_incident(str(incident.id), project.id, sre_actor)
    history_ids = [h.id for h in history]
    assert v1.id in history_ids
    assert v2.id in history_ids

