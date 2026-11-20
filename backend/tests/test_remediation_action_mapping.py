"""Regression tests for AI recommendation action mapping and safe execution.

Verifies:
1. AI recommendation mapping:
   - configuration -> action_name=None (advisory only)
   - restart -> RESTART_SERVICE
   - scaling -> SCALE_REPLICAS
   - rollback -> ROLLBACK_DEPLOYMENT
   - failover -> DRAIN_TRAFFIC
2. Full metadata preservation for advisory configuration recommendations.
3. Execution rejection:
   - Recommendations with action_name=None cannot be executed, even when APPROVED.
   - Rejection occurs before atomic claim, DB state transition, or service dispatch.
   - Recommendation status remains APPROVED and execution_attempt_id remains None.
4. Human approval requirement is preserved:
   - Unapproved (PROPOSED) advisory recommendation fails at approval check first.
5. Explicit RESET_SERVICE_FAULTS execution continues to work normally.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedActor, OperatorRole
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.investigation import Investigation
from app.models.project import Project
from app.models.recommendation import Recommendation
from app.schemas.investigation import (
    EvidenceReference,
    InvestigationResult,
    InvestigationStep,
    RemediationActionType,
    RemediationRecommendation,
    RiskLevel,
    RootCauseEvidenceExplanation,
    TimelineEvidenceEvent,
    UncertaintyGap,
)
from app.schemas.recommendation import (
    AllowlistedAction,
    RemediationApproveRequest,
    RemediationExecuteRequest,
    RemediationExecutionMode,
    RemediationStatus,
)
from app.services.investigation.provider import (
    InvestigationProvider,
    InvestigationProviderResult,
)
from app.services.investigation.service import InvestigationService
from app.services.remediation.exceptions import (
    ActionNotAllowlistedError,
    AdvisoryRecommendationError,
    InvalidRemediationStateError,
)
from app.services.remediation.service import RemediationService
from tests.test_investigation_gemini import _setup_test_correlation_group


class MappingTestMockProvider(InvestigationProvider):
    """Returns an investigation result containing all five action types to test mapping behavior."""

    def __init__(self):
        pass

    def is_configured(self) -> bool:
        return True

    async def generate_investigation(self, evidence, force_regenerate: bool = False) -> InvestigationProviderResult:
        ev1 = evidence.participating_events[0]
        top_cand = evidence.ranked_candidates[0]

        result = InvestigationResult(
            incident_summary="Test multi-action incident summary for remediation mapping verification.",
            conclusion_status="CONCLUSIVE",
            confidence_level="HIGH",
            confidence_explanation="Verified test telemetry",
            timeline=[
                TimelineEvidenceEvent(
                    timestamp=ev1.occurred_at,
                    event_id=ev1.event_id,
                    service_id=ev1.service_id,
                    service_name=ev1.service_name,
                    metric_name=ev1.metric_name,
                    observation="Observed latency spike",
                    severity=ev1.severity,
                )
            ],
            root_cause_analysis=RootCauseEvidenceExplanation(
                candidate_id=top_cand.candidate_id,
                service_id=top_cand.service_id,
                service_name=top_cand.service_name,
                explanation="Root cause candidate verified in test setup",
                contributing_factors=["Connection pool saturation"],
            ),
            evidence_references=[
                EvidenceReference(
                    source_record_type="anomaly_event",
                    source_id=ev1.event_id,
                    supported_field="observed_value",
                    summary_citation="Observed latency 450ms",
                )
            ],
            remediation_recommendations=[
                RemediationRecommendation(
                    title="Optimize Connection Pool Configuration",
                    action_type=RemediationActionType.CONFIGURATION,
                    target_service=ev1.service_name,
                    description="Adjust connection timeout from 8000ms to 2000ms and max idle connections.",
                    risk_level=RiskLevel.LOW,
                    preconditions=["Check database client library compatibility"],
                    rollback_procedure="Revert connection pool settings in config map",
                    expected_result="Connection pool wait time drops below 50ms",
                    verification_steps=["Inspect pool metric wait_time_ms", "Verify no leaked connections"],
                    requires_human_approval=True,
                    command_snippet=None,
                ),
                RemediationRecommendation(
                    title="Restart Problematic Service Pods",
                    action_type=RemediationActionType.RESTART,
                    target_service=ev1.service_name,
                    description="Gracefully restart pods to clear in-memory thread lock contention.",
                    risk_level=RiskLevel.MEDIUM,
                    preconditions=["Confirm active replica count > 1"],
                    rollback_procedure="Restart previous deployment replica set",
                    expected_result="Thread contention resolves and CPU returns to baseline",
                    verification_steps=["Check pod restart count", "Verify /health response"],
                    requires_human_approval=True,
                    command_snippet=None,
                ),
                RemediationRecommendation(
                    title="Scale Service Replicas Out",
                    action_type=RemediationActionType.SCALING,
                    target_service=ev1.service_name,
                    description="Scale deployment replicas from 2 to 4 to handle queue backlog.",
                    risk_level=RiskLevel.LOW,
                    preconditions=["Verify cluster resource quotas"],
                    rollback_procedure="Scale replicas back down to 2",
                    expected_result="Queue latency subsides to <100ms",
                    verification_steps=["Check replica status in cluster", "Monitor P95 latency"],
                    requires_human_approval=True,
                    command_snippet=None,
                ),
                RemediationRecommendation(
                    title="Rollback Recent Service Deployment",
                    action_type=RemediationActionType.ROLLBACK,
                    target_service=ev1.service_name,
                    description="Roll back to previous stable release v1.0.8.",
                    risk_level=RiskLevel.HIGH,
                    preconditions=["Verify database schema backwards-compatibility"],
                    rollback_procedure="Re-deploy target release v1.0.9 if rollback causes regressions",
                    expected_result="Error rate drops to zero",
                    verification_steps=["Verify deployment revision", "Send test transaction"],
                    requires_human_approval=True,
                    command_snippet=None,
                ),
                RemediationRecommendation(
                    title="Drain Traffic from Failing Zone",
                    action_type=RemediationActionType.FAILOVER,
                    target_service=ev1.service_name,
                    description="Drain ingress traffic from zone-b to zone-a.",
                    risk_level=RiskLevel.MEDIUM,
                    preconditions=["Verify target zone capacity"],
                    rollback_procedure="Re-enable routing to zone-b",
                    expected_result="Zone-b traffic drops to 0 and zone-a handles load safely",
                    verification_steps=["Check zone ingress metrics", "Monitor zone-a error rate"],
                    requires_human_approval=True,
                    command_snippet=None,
                ),
            ],
        )
        return InvestigationProviderResult(
            result=result,
            provider="test-mapping-provider",
            model_name="test-model",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            latency_ms=150,
        )


@pytest.fixture
def sre_actor(db_session: Session) -> AuthenticatedActor:
    project = db_session.query(Project).filter(Project.slug == "core-ecommerce").first()
    return AuthenticatedActor(
        actor_id="usr_alex_chen",
        name="Alex Chen",
        email="alex.chen@tracemind.io",
        role=OperatorRole.LEAD_SRE,
        allowed_project_ids={project.id},
    )


# =============================================================================
# 1. AI Recommendation Mapping Tests
# =============================================================================

@pytest.mark.asyncio
async def test_ai_recommendation_action_mapping_persists_correctly(db_session: Session):
    """Proves:
    1. configuration -> action_name=None (advisory only).
    2. restart -> RESTART_SERVICE.
    3. scaling -> SCALE_REPLICAS.
    4. rollback -> ROLLBACK_DEPLOYMENT.
    5. failover -> DRAIN_TRAFFIC.
    6. All metadata (title, description, risk, preconditions, etc.) is preserved.
    """
    proj, group = _setup_test_correlation_group(db_session)
    provider = MappingTestMockProvider()
    service = InvestigationService(db_session, provider=provider)

    inv = await service.get_or_create_investigation(group.id, proj.id)
    assert inv.status == "COMPLETED"

    # Query all persisted recommendations for this investigation
    recs = (
        db_session.query(Recommendation)
        .filter(Recommendation.investigation_id == inv.id)
        .order_by(Recommendation.created_at.asc())
        .all()
    )
    assert len(recs) == 5

    rec_by_title = {r.title: r for r in recs}

    # 1. configuration -> action_name is None (advisory)
    cfg_rec = rec_by_title["Optimize Connection Pool Configuration"]
    assert cfg_rec.action_type == "configuration"
    assert cfg_rec.action_name is None
    assert cfg_rec.status == "PROPOSED"
    assert cfg_rec.risk_level == "LOW"
    assert cfg_rec.requires_human_approval is True
    assert cfg_rec.target_service == "Inventory Service"
    assert "Adjust connection timeout" in cfg_rec.description
    assert cfg_rec.preconditions == ["Check database client library compatibility"]
    assert cfg_rec.rollback_procedure == "Revert connection pool settings in config map"
    assert cfg_rec.expected_result == "Connection pool wait time drops below 50ms"
    assert cfg_rec.verification_steps == ["Inspect pool metric wait_time_ms", "Verify no leaked connections"]

    # 2. restart -> RESTART_SERVICE
    rst_rec = rec_by_title["Restart Problematic Service Pods"]
    assert rst_rec.action_type == "restart"
    assert rst_rec.action_name == AllowlistedAction.RESTART_SERVICE.value
    assert rst_rec.status == "PROPOSED"

    # 3. scaling -> SCALE_REPLICAS
    scl_rec = rec_by_title["Scale Service Replicas Out"]
    assert scl_rec.action_type == "scaling"
    assert scl_rec.action_name == AllowlistedAction.SCALE_REPLICAS.value
    assert scl_rec.status == "PROPOSED"

    # 4. rollback -> ROLLBACK_DEPLOYMENT
    rb_rec = rec_by_title["Rollback Recent Service Deployment"]
    assert rb_rec.action_type == "rollback"
    assert rb_rec.action_name == AllowlistedAction.ROLLBACK_DEPLOYMENT.value
    assert rb_rec.status == "PROPOSED"

    # 5. failover -> DRAIN_TRAFFIC
    fo_rec = rec_by_title["Drain Traffic from Failing Zone"]
    assert fo_rec.action_type == "failover"
    assert fo_rec.action_name == AllowlistedAction.DRAIN_TRAFFIC.value
    assert fo_rec.status == "PROPOSED"


# =============================================================================
# 2. Advisory Recommendation Execution Rejection Tests
# =============================================================================

def test_approved_advisory_recommendation_cannot_be_executed(db_session: Session, sre_actor):
    """Proves:
    1. A recommendation with action_name=None cannot be executed even if status=APPROVED.
    2. Rejection raises AdvisoryRecommendationError / ActionNotAllowlistedError.
    3. Rejected execution does not change recommendation status or create an execution attempt.
    """
    project = db_session.query(Project).filter(Project.slug == "core-ecommerce").first()
    incident = db_session.query(Incident).filter(Incident.project_id == project.id).first()
    remediation_svc = RemediationService(db_session)

    # Create advisory recommendation with action_name=None
    advisory_rec = Recommendation(
        investigation_id=uuid4(),
        incident_id=incident.id,
        project_id=project.id,
        title="Apply Advisory Cache TTL Tuning",
        action_type="configuration",
        action_name=None,
        target_service="order-service",
        description="Tune redis TTL parameters; advisory human intervention required.",
        risk_level="LOW",
        status=RemediationStatus.PROPOSED.value,
        is_dry_run_safe=True,
        requires_human_approval=True,
        is_demo=False,
    )
    db_session.add(advisory_rec)
    db_session.commit()
    db_session.refresh(advisory_rec)

    # 1. Operator explicitly approves the advisory recommendation
    approve_req = RemediationApproveRequest(approval_notes="Reviewed and approved advisory recommendation.")
    remediation_svc.approve_remediation(advisory_rec.id, approve_req, project.id, sre_actor)
    db_session.refresh(advisory_rec)
    assert advisory_rec.status == RemediationStatus.APPROVED.value

    # 2. Operator attempts execution -> must be rejected with domain-level error
    exec_req = RemediationExecuteRequest(execution_mode=RemediationExecutionMode.SIMULATED)
    with pytest.raises(ActionNotAllowlistedError) as exc_info:
        remediation_svc.execute_remediation(advisory_rec.id, exec_req, project.id, sre_actor)

    # Check error message and type
    assert isinstance(exc_info.value, AdvisoryRecommendationError)
    assert "advisory" in str(exc_info.value).lower()
    assert "action_name is null" in str(exc_info.value).lower()

    # 3. Verify state invariants: status remains APPROVED, no attempt id, no execution trace
    db_session.refresh(advisory_rec)
    assert advisory_rec.status == RemediationStatus.APPROVED.value
    assert advisory_rec.execution_attempt_id is None
    assert advisory_rec.executed_by is None
    assert advisory_rec.executed_at is None
    assert advisory_rec.execution_started_at is None

    # Verify no execution audit event was created
    exec_events = (
        db_session.query(IncidentEvent)
        .filter(
            IncidentEvent.incident_id == incident.id,
            IncidentEvent.title.like("%Execution Started%"),
        )
        .all()
    )
    assert len(exec_events) == 0


def test_unapproved_advisory_recommendation_fails_approval_check_first(db_session: Session, sre_actor):
    """Proves that an unapproved (PROPOSED) advisory recommendation is rejected by the
    mandatory human approval guard before reaching the allowlist validation.
    """
    project = db_session.query(Project).filter(Project.slug == "core-ecommerce").first()
    incident = db_session.query(Incident).filter(Incident.project_id == project.id).first()
    remediation_svc = RemediationService(db_session)

    advisory_rec = Recommendation(
        investigation_id=uuid4(),
        incident_id=incident.id,
        project_id=project.id,
        title="Unapproved Advisory Action",
        action_type="configuration",
        action_name=None,
        target_service="order-service",
        description="Advisory configuration update.",
        risk_level="LOW",
        status=RemediationStatus.PROPOSED.value,
        is_dry_run_safe=True,
        requires_human_approval=True,
        is_demo=False,
    )
    db_session.add(advisory_rec)
    db_session.commit()
    db_session.refresh(advisory_rec)

    exec_req = RemediationExecuteRequest()
    with pytest.raises(InvalidRemediationStateError) as exc_info:
        remediation_svc.execute_remediation(advisory_rec.id, exec_req, project.id, sre_actor)

    assert "explicit human approval before execution" in str(exc_info.value)
    db_session.refresh(advisory_rec)
    assert advisory_rec.status == RemediationStatus.PROPOSED.value
    assert advisory_rec.execution_attempt_id is None


# =============================================================================
# 3. Explicit Allowlisted Execution Continues to Work
# =============================================================================

def test_existing_explicit_reset_service_faults_execution_continues_to_work(db_session: Session, sre_actor):
    """Proves: Existing explicit RESET_SERVICE_FAULTS execution continues to function properly."""
    project = db_session.query(Project).filter(Project.slug == "core-ecommerce").first()
    incident = db_session.query(Incident).filter(Incident.project_id == project.id).first()
    remediation_svc = RemediationService(db_session)

    rec = Recommendation(
        investigation_id=uuid4(),
        incident_id=incident.id,
        project_id=project.id,
        title="Reset Payment Service Faults",
        action_type="configuration",
        action_name=AllowlistedAction.RESET_SERVICE_FAULTS.value,
        target_service="payment-service",
        description="Explicit fault reset recommendation.",
        risk_level="LOW",
        status=RemediationStatus.PROPOSED.value,
        is_dry_run_safe=True,
        requires_human_approval=True,
        is_demo=False,
    )
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)

    # Approve
    remediation_svc.approve_remediation(rec.id, RemediationApproveRequest(approval_notes="OK"), project.id, sre_actor)
    db_session.refresh(rec)
    assert rec.status == RemediationStatus.APPROVED.value

    # Execute in SIMULATED mode
    res = remediation_svc.execute_remediation(
        rec.id,
        RemediationExecuteRequest(execution_mode=RemediationExecutionMode.SIMULATED),
        project.id,
        sre_actor,
    )
    assert res.status == RemediationStatus.EXECUTED
    db_session.refresh(rec)
    assert rec.status == RemediationStatus.EXECUTED.value
    assert rec.execution_attempt_id is not None
    assert rec.executed_by == sre_actor.name


# =============================================================================
# 4. API Layer Route Test
# =============================================================================

def test_api_execute_advisory_recommendation_returns_400(client: TestClient, db_session: Session):
    """Verifies HTTP 400 Bad Request with clear detail when attempting execution via API."""
    project = db_session.query(Project).filter(Project.slug == "core-ecommerce").first()
    incident = db_session.query(Incident).filter(Incident.project_id == project.id).first()

    rec = Recommendation(
        investigation_id=uuid4(),
        incident_id=incident.id,
        project_id=project.id,
        title="Advisory Database Index Tuning",
        action_type="configuration",
        action_name=None,
        target_service="inventory-service",
        description="Add composite index on (order_id, status). Advisory only.",
        risk_level="LOW",
        status=RemediationStatus.APPROVED.value,
        approved_by="Alex Chen",
        is_dry_run_safe=True,
        requires_human_approval=True,
        is_demo=False,
    )
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)

    headers = {"Authorization": "Bearer tracemind-sre-token"}
    resp = client.post(
        f"/api/v1/remediations/{rec.id}/execute?project_id={project.id}",
        json={"execution_mode": "SIMULATED"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "advisory" in resp.json()["detail"].lower()
    assert "action_name is null" in resp.json()["detail"].lower()
