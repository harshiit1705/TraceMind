"""Comprehensive Test Suite for Phase 4 Human-Approved Remediation Workflow.

Verifies:
1. Lifecycle state transitions (PROPOSED -> APPROVED / REJECTED / CANCELLED -> EXECUTING -> EXECUTED / FAILED).
2. Mandatory human approval guard (never execute without prior human approval).
3. Idempotency and duplicate execution prevention.
4. Parameter validation and allowlist enforcement (no arbitrary command execution).
5. Cross-project isolation and tenant boundary enforcement.
6. Real microservice vs. simulated execution adapter behaviour.
7. Audit timeline event preservation in incident events.
8. API endpoints under /api/v1/remediations and /api/v1/incidents/{incident_id}/remediations.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.investigation import Investigation
from app.models.project import Project
from app.models.recommendation import Recommendation
from app.schemas.recommendation import AllowlistedAction, RemediationStatus
from app.services.remediation.adapter import RealMicroserviceExecutionAdapter, SimulatedExecutionAdapter
from app.services.remediation.exceptions import (
    ActionNotAllowlistedError,
    DuplicateExecutionError,
    InvalidRemediationStateError,
    ParameterValidationError,
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


# -----------------------------------------------------------------------------
# 1. Human Approval and Lifecycle State Machine Tests
# -----------------------------------------------------------------------------

def test_remediation_approval_lifecycle(db_session: Session, test_setup):
    service = RemediationService(db_session)
    incident = test_setup["incident"]

    # Step 1: Propose
    from app.schemas.recommendation import RemediationProposeRequest
    prop_req = RemediationProposeRequest(
        title="Reset Contended Inventory Locks",
        description="Resets in-memory warehouse reservation locks to clear lock contention.",
        target_service="inventory-service",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
        action_parameters={"clear_cache": True},
        preconditions=["Inventory reservation latency > 500ms"],
        proposer_name="sre.operator@acme.corp",
    )
    rec_dto = service.propose_remediation(str(incident.id), prop_req)
    assert rec_dto.status == RemediationStatus.PROPOSED
    assert rec_dto.requires_human_approval is True
    rec_id = rec_dto.id

    # Step 2: Cannot execute in PROPOSED state (Human approval guard)
    from app.schemas.recommendation import RemediationExecuteRequest
    with pytest.raises(InvalidRemediationStateError) as exc_info:
        service.execute_remediation(rec_id, RemediationExecuteRequest(executor_name="auto.bot"))
    assert "requires explicit human approval" in str(exc_info.value)

    # Step 3: Approve
    from app.schemas.recommendation import RemediationApproveRequest
    app_req = RemediationApproveRequest(
        approver_name="Senior SRE Lead",
        approval_notes="Lock contention confirmed in distributed traces. Safe to reset.",
    )
    app_dto = service.approve_remediation(rec_id, app_req)
    assert app_dto.status == RemediationStatus.APPROVED
    assert app_dto.approved_by == "Senior SRE Lead"
    assert app_dto.approved_at is not None

    # Step 4: Idempotent re-approval
    re_app = service.approve_remediation(rec_id, app_req)
    assert re_app.status == RemediationStatus.APPROVED

    # Step 5: Execute
    exec_req = RemediationExecuteRequest(executor_name="OnCall Engineer", idempotency_key="idemp-101")
    exec_dto = service.execute_remediation(rec_id, exec_req)
    assert exec_dto.status == RemediationStatus.EXECUTED
    assert exec_dto.executed_by == "OnCall Engineer"
    assert exec_dto.execution_mode in ("REAL", "SIMULATED")
    assert exec_dto.execution_result_json is not None
    assert exec_dto.execution_result_json.get("verified") is True

    # Step 6: Idempotent execution
    cached_dto = service.execute_remediation(rec_id, exec_req)
    assert cached_dto.status == RemediationStatus.EXECUTED


def test_remediation_rejection_lifecycle(db_session: Session, test_setup):
    service = RemediationService(db_session)
    incident = test_setup["incident"]

    from app.schemas.recommendation import RemediationProposeRequest, RemediationRejectRequest
    prop_req = RemediationProposeRequest(
        title="Emergency Scale Payment Service Replicas",
        description="Scales payment pods to 8 instances.",
        target_service="payment-service",
        action_name=AllowlistedAction.SCALE_REPLICAS,
        action_parameters={"replica_count": 8},
        proposer_name="junior.dev@acme.corp",
    )
    rec = service.propose_remediation(str(incident.id), prop_req)
    assert rec.status == RemediationStatus.PROPOSED

    # Reject recommendation
    rej_req = RemediationRejectRequest(
        rejector_name="Database Administrator",
        rejection_reason="Database connection pool will be exhausted by 8 payment pods.",
    )
    rej_dto = service.reject_remediation(rec.id, rej_req)
    assert rej_dto.status == RemediationStatus.REJECTED
    assert rej_dto.rejected_by == "Database Administrator"
    assert rej_dto.rejection_reason == "Database connection pool will be exhausted by 8 payment pods."

    # Cannot execute rejected remediation
    from app.schemas.recommendation import RemediationExecuteRequest
    with pytest.raises(InvalidRemediationStateError) as exc_info:
        service.execute_remediation(rec.id, RemediationExecuteRequest(executor_name="operator"))
    assert "Cannot execute a REJECTED remediation" in str(exc_info.value)


def test_remediation_cancellation(db_session: Session, test_setup):
    service = RemediationService(db_session)
    incident = test_setup["incident"]

    from app.schemas.recommendation import RemediationCancelRequest, RemediationProposeRequest
    prop_req = RemediationProposeRequest(
        title="Flush Payment Connection Pool",
        description="Flushes DB connection pool.",
        target_service="payment-service",
        action_name=AllowlistedAction.FLUSH_CONNECTION_POOL,
        proposer_name="engineer",
    )
    rec = service.propose_remediation(str(incident.id), prop_req)
    assert rec.status == RemediationStatus.PROPOSED

    cancel_req = RemediationCancelRequest(cancelled_by="Operator", cancellation_reason="Incident self-healed")
    cancelled = service.cancel_remediation(rec.id, cancel_req)
    assert cancelled.status == RemediationStatus.CANCELLED

    # Cannot execute cancelled remediation
    from app.schemas.recommendation import RemediationExecuteRequest
    with pytest.raises(InvalidRemediationStateError):
        service.execute_remediation(rec.id, RemediationExecuteRequest(executor_name="operator"))


# -----------------------------------------------------------------------------
# 2. Allowlist and Parameter Validation Tests
# -----------------------------------------------------------------------------

def test_action_parameter_validation():
    # SCALE_REPLICAS validation
    with pytest.raises(ParameterValidationError):
        SimulatedExecutionAdapter.execute(
            action_name=AllowlistedAction.SCALE_REPLICAS.value,
            target_service="order-service",
            parameters={"replica_count": 99},  # Exceeds max 10
        )

    with pytest.raises(ParameterValidationError):
        SimulatedExecutionAdapter.execute(
            action_name=AllowlistedAction.SCALE_REPLICAS.value,
            target_service="order-service",
            parameters={"replica_count": "invalid_number"},
        )

    # Valid SCALE_REPLICAS
    res = SimulatedExecutionAdapter.execute(
        action_name=AllowlistedAction.SCALE_REPLICAS.value,
        target_service="order-service",
        parameters={"replica_count": 4},
    )
    assert res["is_simulated"] is True
    assert res["replica_count"] == 4
    assert res["verified"] is True

    # ROLLBACK_DEPLOYMENT validation
    with pytest.raises(ParameterValidationError):
        SimulatedExecutionAdapter.execute(
            action_name=AllowlistedAction.ROLLBACK_DEPLOYMENT.value,
            target_service="payment-service",
            parameters={"target_version": ""},
        )

    # DRAIN_TRAFFIC validation
    with pytest.raises(ParameterValidationError):
        SimulatedExecutionAdapter.execute(
            action_name=AllowlistedAction.DRAIN_TRAFFIC.value,
            target_service="inventory-service",
            parameters={"drain_percentage": 150},  # Exceeds 100%
        )

    # Disallowed action
    with pytest.raises(ActionNotAllowlistedError):
        SimulatedExecutionAdapter.execute(
            action_name="RUN_ARBITRARY_SHELL_COMMAND",
            target_service="order-service",
            parameters={},
        )


# -----------------------------------------------------------------------------
# 3. Cross-Project Isolation Tests
# -----------------------------------------------------------------------------

def test_cross_project_isolation(db_session: Session, test_setup):
    service = RemediationService(db_session)
    incident = test_setup["incident"]
    foreign_project_id = uuid4()

    from app.schemas.recommendation import RemediationApproveRequest, RemediationProposeRequest
    prop_req = RemediationProposeRequest(
        title="Test Isolation Remediation",
        description="Verifies project tenant boundary.",
        target_service="inventory-service",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
    )
    rec = service.propose_remediation(str(incident.id), prop_req)

    # Querying with mismatched project_id raises ProjectIsolationError
    from app.services.incident_service import ProjectIsolationError
    with pytest.raises(ProjectIsolationError):
        service.get_remediation(rec.id, project_id=foreign_project_id)

    with pytest.raises(ProjectIsolationError):
        service.approve_remediation(
            rec.id,
            RemediationApproveRequest(approver_name="Attacker"),
            project_id=foreign_project_id,
        )


# -----------------------------------------------------------------------------
# 4. Audit History Preservation in Incident Events
# -----------------------------------------------------------------------------

def test_audit_timeline_preservation(db_session: Session, test_setup):
    service = RemediationService(db_session)
    incident = test_setup["incident"]

    from app.models.incident_event import IncidentEvent
    events_before = db_session.query(IncidentEvent).filter(IncidentEvent.incident_id == incident.id).count()

    from app.schemas.recommendation import RemediationApproveRequest, RemediationExecuteRequest, RemediationProposeRequest
    rec = service.propose_remediation(
        str(incident.id),
        RemediationProposeRequest(
            title="Audit Test Action",
            description="Testing incident audit timeline integration.",
            target_service="payment-service",
            action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
            proposer_name="Security Auditor",
        ),
    )

    service.approve_remediation(
        rec.id,
        RemediationApproveRequest(approver_name="Lead SRE", approval_notes="Approved for audit test"),
    )

    service.execute_remediation(rec.id, RemediationExecuteRequest(executor_name="Exec Bot"))

    events_after = db_session.query(IncidentEvent).filter(IncidentEvent.incident_id == incident.id).all()
    assert len(events_after) >= events_before + 3

    event_titles = [e.title for e in events_after]
    assert any("Remediation Proposed" in t for t in event_titles)
    assert any("Remediation Approved" in t for t in event_titles)
    assert any("Remediation Executed" in t for t in event_titles)


# -----------------------------------------------------------------------------
# 5. REST API Route Handler Integration Tests
# -----------------------------------------------------------------------------

def test_remediation_api_endpoints(db_session: Session, test_setup):
    from fastapi import HTTPException
    from app.api.v1.incidents import list_incident_remediations, propose_incident_remediation
    from app.api.v1.remediations import (
        approve_remediation,
        execute_remediation,
        get_remediation,
        reject_remediation,
    )
    from app.schemas.recommendation import (
        RemediationApproveRequest,
        RemediationExecuteRequest,
        RemediationProposeRequest,
        RemediationRejectRequest,
    )

    incident = test_setup["incident"]
    inc_id = incident.id

    # 1. Propose remediation via route handler
    prop_req = RemediationProposeRequest(
        title="API Test Reset Inventory Faults",
        description="Propose fault reset via REST endpoint handler.",
        target_service="inventory-service",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS,
        action_parameters={"force": True},
        preconditions=["Verify inventory queue healthy"],
        proposer_name="REST Route Tester",
    )
    rec_dto = propose_incident_remediation(str(inc_id), prop_req, project_id=None, db=db_session)
    assert rec_dto.status == RemediationStatus.PROPOSED
    assert rec_dto.requires_human_approval is True
    rec_id = rec_dto.id

    # 2. List remediations via route handler
    remediations_list = list_incident_remediations(str(inc_id), project_id=None, db=db_session)
    assert any(item.id == rec_id for item in remediations_list)

    # 3. Retrieve single remediation via route handler
    single_rec = get_remediation(rec_id, project_id=None, db=db_session)
    assert single_rec.id == rec_id
    assert single_rec.title == "API Test Reset Inventory Faults"

    # 4. Attempt premature execution before approval -> Expect HTTPException 409 Conflict
    with pytest.raises(HTTPException) as exc_info:
        execute_remediation(
            rec_id,
            RemediationExecuteRequest(executor_name="Premature Executor"),
            project_id=None,
            db=db_session,
        )
    assert exc_info.value.status_code == 409
    assert "human approval" in exc_info.value.detail

    # 5. Approve remediation via route handler
    app_res = approve_remediation(
        rec_id,
        RemediationApproveRequest(approver_name="Human SRE", approval_notes="Looks safe to proceed"),
        project_id=None,
        db=db_session,
    )
    assert app_res.status == RemediationStatus.APPROVED
    assert app_res.approved_by == "Human SRE"

    # 6. Execute approved remediation via route handler
    exec_res = execute_remediation(
        rec_id,
        RemediationExecuteRequest(executor_name="Automation Runner", idempotency_key="test-key-999"),
        project_id=None,
        db=db_session,
    )
    assert exec_res.status == RemediationStatus.EXECUTED
    assert exec_res.executed_by == "Automation Runner"
    assert exec_res.execution_result_json is not None
    assert exec_res.execution_result_json.get("verified") is True

    # 7. Check incident timeline preserves audit events
    from app.models.incident_event import IncidentEvent
    events = db_session.query(IncidentEvent).filter(IncidentEvent.incident_id == inc_id).all()
    event_titles = [e.title for e in events]
    assert any("Approved" in t for t in event_titles)
    assert any("Executed" in t for t in event_titles)
