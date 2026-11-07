"""Comprehensive test suite for Sprint 5.1: Investigation schemas, evidence builder, and grounding safeguards."""

from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.correlation import CorrelationGroup
from app.models.investigation import Investigation
from app.models.organization import Organization
from app.models.project import Project
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.schemas.correlation import CorrelationEvaluationRequest, CorrelationConfig
from app.schemas.investigation import (
    EvidenceCandidateItem,
    EvidenceDependencyItem,
    EvidenceEventItem,
    EvidencePackage,
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
from app.services.correlation.service import CorrelationService
from app.services.investigation.evidence_builder import EvidenceBuilder, redact_secrets
from app.services.investigation.validator import (
    GroundingValidationError,
    validate_investigation_result_against_evidence,
)


# --- 1. Secret Redaction Tests ---

def test_secret_redaction():
    """Verify credentials and keys are scrubbed while preserving legitimate operational telemetry."""
    # 1. Connection string with password
    uri = "postgresql://db_user:s3cr3t_password@10.0.0.5:5432/orders_db"
    redacted_uri = redact_secrets(uri)
    assert "s3cr3t_password" not in redacted_uri
    assert "postgresql://db_user:[REDACTED_PASSWORD]@10.0.0.5:5432/orders_db" in redacted_uri

    # 2. Bearer token
    bearer = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    redacted_bearer = redact_secrets(bearer)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted_bearer
    assert "Bearer [REDACTED_TOKEN]" in redacted_bearer

    # 3. Known API key formats
    google_key = "AIzaSyD-1234567890abcdefghijklmnopqrstuv"
    assert redact_secrets(google_key) == "[REDACTED_API_KEY]"

    aws_key = "AKIAIOSFODNN7EXAMPLE"
    assert redact_secrets(aws_key) == "[REDACTED_AWS_KEY]"

    github_token = "ghp_123456789012345678901234567890123456"
    assert redact_secrets(github_token) == "[REDACTED_GITHUB_TOKEN]"

    openai_key = "sk-1234567890abcdef1234567890abcdef"
    assert redact_secrets(openai_key) == "[REDACTED_SECRET_KEY]"

    # 4. Standard telemetry names must NOT be redacted
    metric = "order_service.db_connection_pool.active_connections"
    assert redact_secrets(metric) == metric

    service = "payment-gateway-v2"
    assert redact_secrets(service) == service


# --- 2. Investigation Schema & Guard Tests ---

def test_human_approval_enforcement():
    """Remediation recommendations strictly require human approval (cannot be False)."""
    with pytest.raises(ValidationError, match="requires_human_approval"):
        RemediationRecommendation(
            title="Restart Service Pods",
            action_type=RemediationActionType.RESTART,
            target_service="order-service",
            description="Restart pods to relieve connection backlog.",
            risk_level=RiskLevel.MEDIUM,
            preconditions=["Verify read replica is healthy"],
            rollback_procedure="Revert deployment replica count",
            requires_human_approval=False,  # Forbidden!
        )


def test_command_snippet_forbids_executable_snippets():
    """Autonomous execution and executable snippets are strictly prohibited."""
    with pytest.raises(ValidationError, match="Autonomous execution and executable command snippets are strictly prohibited"):
        RemediationRecommendation(
            title="Kill Idle Sessions",
            action_type=RemediationActionType.CONFIGURATION,
            target_service="postgres-primary",
            description="Terminate idle connections.",
            risk_level=RiskLevel.LOW,
            preconditions=["Verify replication lag < 1s"],
            rollback_procedure="None",
            requires_human_approval=True,
            command_snippet="SELECT pg_terminate_backend(pid) FROM pg_stat_activity;",  # Forbidden!
        )


def test_investigation_schema_forbids_extra_fields():
    """Investigation models forbid undeclared / hallucinated fields."""
    with pytest.raises(ValidationError):
        TimelineEvidenceEvent(
            timestamp=datetime.now(timezone.utc),
            event_id=uuid4(),
            service_id=uuid4(),
            service_name="Order Service",
            metric_name="latency",
            observation="Observed spike",
            severity="high",
            hallucinated_field="Dangerous extra data",  # Extra forbidden!
        )


# --- 3. Grounding Validator Tests ---

def _create_sample_evidence_package() -> EvidencePackage:
    ev_id_1 = uuid4()
    ev_id_2 = uuid4()
    svc_id_1 = uuid4()
    svc_id_2 = uuid4()
    cand_id_1 = uuid4()
    cand_id_2 = uuid4()
    group_id = uuid4()
    proj_id = uuid4()

    t0 = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)

    return EvidencePackage(
        package_version="1.0",
        correlation_group_id=group_id,
        project_id=proj_id,
        project_slug="test-proj",
        project_name="Test Project",
        time_window_start=t0,
        time_window_end=t0 + timedelta(minutes=5),
        confidence_score=0.92,
        topology_complete=True,
        topology_status_explanation="Verified DAG",
        participating_events=[
            EvidenceEventItem(
                event_id=ev_id_1,
                service_id=svc_id_1,
                service_name="Inventory Service",
                service_identifier="svc:inventory",
                metric_name="latency",
                observed_value=500.0,
                expected_baseline=50.0,
                deviation_pct=900.0,
                severity="critical",
                detection_method="rolling_average",
                occurred_at=t0,
                relevance_score=1.0,
                correlation_reason="Initiating anomaly",
                has_persisted_baseline=True,
                baseline_mean=50.0,
                baseline_std_dev=5.0,
            ),
            EvidenceEventItem(
                event_id=ev_id_2,
                service_id=svc_id_2,
                service_name="Order Service",
                service_identifier="svc:order",
                metric_name="latency",
                observed_value=800.0,
                expected_baseline=80.0,
                deviation_pct=900.0,
                severity="high",
                detection_method="rolling_average",
                occurred_at=t0 + timedelta(seconds=30),
                relevance_score=0.90,
                correlation_reason="Downstream cascade",
                has_persisted_baseline=True,
                baseline_mean=80.0,
                baseline_std_dev=8.0,
            ),
        ],
        service_dependencies=[
            EvidenceDependencyItem(
                source_service_id=svc_id_2,
                source_service_name="Order Service",
                target_service_id=svc_id_1,
                target_service_name="Inventory Service",
                dependency_type="sync",
                description="Order calls inventory synchronously",
            )
        ],
        ranked_candidates=[
            EvidenceCandidateItem(
                candidate_id=cand_id_1,
                service_id=svc_id_1,
                service_name="Inventory Service",
                service_identifier="svc:inventory",
                rank=1,
                score=0.92,
                confidence="HIGH",
                is_probable_root_cause=True,
                temporal_precedence_score=1.0,
                topological_score=1.0,
                blast_radius_score=1.0,
                severity_score=0.85,
            ),
            EvidenceCandidateItem(
                candidate_id=cand_id_2,
                service_id=svc_id_2,
                service_name="Order Service",
                service_identifier="svc:order",
                rank=2,
                score=0.45,
                confidence="LOW",
                is_probable_root_cause=False,
                temporal_precedence_score=0.0,
                topological_score=0.10,
                blast_radius_score=0.0,
                severity_score=0.85,
            ),
        ],
        missing_evidence=[],
        unobserved_telemetry=["Raw application logs are uninstrumented."],
        evidence_hash="sample_hash_123",
    )


def test_grounding_validator_accepts_valid_references():
    """Grounded result citing authentic event IDs and candidate IDs passes validation."""
    evidence = _create_sample_evidence_package()
    ev1 = evidence.participating_events[0]
    ev2 = evidence.participating_events[1]
    top_cand = evidence.ranked_candidates[0]

    result = InvestigationResult(
        incident_summary="Inventory Service experienced latency degradation which cascaded to Order Service within 30s.",
        timeline=[
            TimelineEvidenceEvent(
                timestamp=ev1.occurred_at,
                event_id=ev1.event_id,
                service_id=ev1.service_id,
                service_name=ev1.service_name,
                metric_name=ev1.metric_name,
                observation="Inventory latency spiked to 500ms (+900% above baseline).",
                severity=ev1.severity,
            ),
            TimelineEvidenceEvent(
                timestamp=ev2.occurred_at,
                event_id=ev2.event_id,
                service_id=ev2.service_id,
                service_name=ev2.service_name,
                metric_name=ev2.metric_name,
                observation="Order Service latency degraded to 800ms (+900% above baseline).",
                severity=ev2.severity,
            ),
        ],
        root_cause_analysis=RootCauseEvidenceExplanation(
            candidate_id=top_cand.candidate_id,
            service_id=top_cand.service_id,
            service_name=top_cand.service_name,
            explanation="Inventory Service is the initiating upstream dependency with peak severity and blast radius.",
            contributing_factors=["Downstream callers lack circuit breakers."],
        ),
        evidence_references=[
            EvidenceReference(
                source_record_type="anomaly_event",
                source_id=ev1.event_id,
                supported_field="observed_value",
                summary_citation="Inventory latency observed at 500.0ms",
            )
        ],
        uncertainties_and_gaps=[
            UncertaintyGap(
                category="missing_telemetry",
                description="Database host memory telemetry is unobserved.",
                impact_on_confidence="Moderate",
            )
        ],
        prioritized_investigation_steps=[
            InvestigationStep(
                step_number=1,
                target_service="Inventory Service",
                action="Inspect inventory database connection pool metrics",
                purpose="Confirm if pool exhaustion caused thread blocking",
            )
        ],
        remediation_recommendations=[
            RemediationRecommendation(
                title="Scale Inventory Service Replicas",
                action_type=RemediationActionType.SCALING,
                target_service="Inventory Service",
                description="Increase replica count from 2 to 4 to handle load.",
                risk_level=RiskLevel.LOW,
                preconditions=["Verify cluster compute capacity"],
                rollback_procedure="Scale replicas back to 2",
                requires_human_approval=True,
                command_snippet=None,
            )
        ],
    )

    # Must pass without raising GroundingValidationError
    validate_investigation_result_against_evidence(result, evidence)


def test_grounding_validator_rejects_foreign_anomaly_event_id():
    """Timeline event referencing a foreign / hallucinated event_id must fail validation."""
    evidence = _create_sample_evidence_package()
    fake_event_id = uuid4()
    top_cand = evidence.ranked_candidates[0]

    result = InvestigationResult(
        incident_summary="Summary with hallucinated event reference.",
        timeline=[
            TimelineEvidenceEvent(
                timestamp=datetime.now(timezone.utc),
                event_id=fake_event_id,  # Hallucinated!
                service_id=top_cand.service_id,
                service_name="Inventory Service",
                metric_name="latency",
                observation="Spike observed.",
                severity="critical",
            )
        ],
        root_cause_analysis=RootCauseEvidenceExplanation(
            candidate_id=top_cand.candidate_id,
            service_id=top_cand.service_id,
            service_name=top_cand.service_name,
            explanation="Upstream origin.",
        ),
    )

    with pytest.raises(GroundingValidationError, match="foreign or hallucinated anomaly event ID"):
        validate_investigation_result_against_evidence(result, evidence)


def test_grounding_validator_rejects_invalid_candidate_reference():
    """Root cause explanation referencing unknown candidate ID must fail validation."""
    evidence = _create_sample_evidence_package()
    ev1 = evidence.participating_events[0]
    fake_candidate_id = uuid4()

    result = InvestigationResult(
        incident_summary="Summary with fake candidate ID.",
        timeline=[
            TimelineEvidenceEvent(
                timestamp=ev1.occurred_at,
                event_id=ev1.event_id,
                service_id=ev1.service_id,
                service_name=ev1.service_name,
                metric_name=ev1.metric_name,
                observation="Spike observed.",
                severity=ev1.severity,
            )
        ],
        root_cause_analysis=RootCauseEvidenceExplanation(
            candidate_id=fake_candidate_id,  # Foreign!
            service_id=ev1.service_id,
            service_name="Inventory Service",
            explanation="Explanation citing unknown candidate.",
        ),
    )

    with pytest.raises(GroundingValidationError, match="does not exist among the deterministic ranked candidates"):
        validate_investigation_result_against_evidence(result, evidence)


def test_grounding_validator_rejects_candidate_service_id_mismatch():
    """Root cause explanation where candidate_id does not match service_id must fail validation."""
    evidence = _create_sample_evidence_package()
    ev1 = evidence.participating_events[0]
    top_cand = evidence.ranked_candidates[0]
    wrong_service_id = uuid4()

    result = InvestigationResult(
        incident_summary="Summary with mismatched candidate service ID.",
        timeline=[
            TimelineEvidenceEvent(
                timestamp=ev1.occurred_at,
                event_id=ev1.event_id,
                service_id=ev1.service_id,
                service_name=ev1.service_name,
                metric_name=ev1.metric_name,
                observation="Spike observed.",
                severity=ev1.severity,
            )
        ],
        root_cause_analysis=RootCauseEvidenceExplanation(
            candidate_id=top_cand.candidate_id,
            service_id=wrong_service_id,  # Mismatched!
            service_name="Order Service",
            explanation="Explanation with mismatched service.",
        ),
    )

    with pytest.raises(GroundingValidationError, match="Candidate service ID mismatch"):
        validate_investigation_result_against_evidence(result, evidence)


# --- 4. Evidence Builder Database Integration Tests ---

def test_evidence_builder_from_persisted_correlation_group(db_session: Session):
    """Builds authentic EvidencePackage from persisted correlation group, events, and candidates."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)

    # Insert baseline for inventory service
    bl = AnomalyBaseline(
        id=uuid4(),
        project_id=proj.id,
        service_id=inv_svc.id,
        metric_name="latency",
        detection_method="rolling_average",
        config_snapshot={},
        baseline_state={"mean": 45.0, "std_dev": 4.5},
        sample_count=30,
        version=1,
    )
    db_session.add(bl)

    # Insert two anomaly events
    ev1 = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=inv_svc.id,
        metric_name="latency",
        observed_value=450.0,
        expected_baseline=45.0,
        deviation_pct=900.0,
        severity="critical",
        detection_method="rolling_average",
        occurred_at=t,
        status="open",
    )
    ev2 = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=order_svc.id,
        metric_name="latency",
        observed_value=900.0,
        expected_baseline=90.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t + timedelta(seconds=20),
        status="open",
    )
    db_session.add_all([ev1, ev2])
    db_session.commit()

    # Run correlation service to evaluate and persist
    corr_svc = CorrelationService(db_session)
    eval_resp = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=proj.id,
            start_time=t - timedelta(minutes=1),
            end_time=t + timedelta(minutes=2),
            config=CorrelationConfig(max_cascade_delay_seconds=300),
        )
    )
    assert eval_resp.correlation_groups_count >= 1
    group_id = eval_resp.groups[0].id

    # Build evidence package using EvidenceBuilder
    builder = EvidenceBuilder(db_session)
    package = builder.build_evidence_package(group_id, expected_project_id=proj.id)

    assert package.correlation_group_id == group_id
    assert package.project_id == proj.id
    assert package.project_slug == "core-ecommerce"
    assert len(package.participating_events) == 2
    assert len(package.ranked_candidates) == 2

    # Verify baseline was resolved for inventory service
    inv_event_item = next(e for e in package.participating_events if e.service_id == inv_svc.id)
    assert inv_event_item.has_persisted_baseline is True
    assert inv_event_item.baseline_mean == 45.0

    # Verify order service lacked baseline and was reported in missing evidence
    order_event_item = next(e for e in package.participating_events if e.service_id == order_svc.id)
    assert order_event_item.has_persisted_baseline is False
    assert any("order-service" in m or "Order Service" in m for m in package.missing_evidence)

    # Verify deterministic evidence hash exists and is 64-char hex
    assert len(package.evidence_hash) == 64


def test_evidence_builder_project_isolation(db_session: Session):
    """Attempting to access a correlation group across project boundaries raises PermissionError."""
    proj1 = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    org = db_session.query(Organization).first()

    proj2 = Project(
        organization_id=org.id,
        slug="isolated-boundary-test",
        name="Isolated Boundary Test",
        environment="test",
    )
    db_session.add(proj2)
    db_session.commit()
    db_session.refresh(proj2)

    svc_p2 = Service(project_id=proj2.id, slug="p2-svc", name="P2 Svc", identifier="svc:p2")
    db_session.add(svc_p2)
    db_session.commit()

    t = datetime(2026, 11, 7, 13, 0, 0, tzinfo=timezone.utc)
    ev = AnomalyEvent(
        id=uuid4(),
        project_id=proj2.id,
        service_id=svc_p2.id,
        metric_name="latency",
        observed_value=300.0,
        expected_baseline=30.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t,
        status="open",
    )
    db_session.add(ev)
    db_session.commit()

    corr_svc = CorrelationService(db_session)
    res = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=proj2.id,
            start_time=t - timedelta(minutes=1),
            end_time=t + timedelta(minutes=1),
            config=CorrelationConfig(min_events_per_group=1),
        )
    )
    assert res.correlation_groups_count == 1
    g2_id = res.groups[0].id

    # Trying to build evidence package for g2 using proj1 credentials must fail
    builder = EvidenceBuilder(db_session)
    with pytest.raises(PermissionError, match="Project isolation violation"):
        builder.build_evidence_package(g2_id, expected_project_id=proj1.id)


def test_evidence_builder_deterministic_serialization_and_hashing(db_session: Session):
    """Calling build_evidence_package repeatedly on identical records produces identical evidence_hash."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()

    t = datetime(2026, 11, 7, 14, 0, 0, tzinfo=timezone.utc)
    ev = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=inv_svc.id,
        metric_name="cpu",
        observed_value=99.0,
        expected_baseline=50.0,
        deviation_pct=98.0,
        severity="critical",
        detection_method="rolling_average",
        occurred_at=t,
        status="open",
    )
    db_session.add(ev)
    db_session.commit()

    corr_svc = CorrelationService(db_session)
    res = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=proj.id,
            start_time=t - timedelta(minutes=1),
            end_time=t + timedelta(minutes=1),
            config=CorrelationConfig(min_events_per_group=1),
        )
    )
    group_id = res.groups[0].id

    builder = EvidenceBuilder(db_session)
    pkg1 = builder.build_evidence_package(group_id)
    pkg2 = builder.build_evidence_package(group_id)

    assert pkg1.evidence_hash == pkg2.evidence_hash
    assert len(pkg1.evidence_hash) == 64


def test_investigation_persistence_model(db_session: Session):
    """Investigation model can be persisted with correlation_group_id and preserves audit history."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    group = CorrelationGroup(
        id=uuid4(),
        project_id=proj.id,
        correlation_key="test_audit_corr_key_123",
        time_window_start=datetime.now(timezone.utc),
        time_window_end=datetime.now(timezone.utc),
        status="ACTIVE",
    )
    db_session.add(group)
    db_session.commit()

    # Create investigation record linked to correlation group
    inv = Investigation(
        id=uuid4(),
        correlation_group_id=group.id,
        incident_id=None,  # Independent of legacy incident
        provider="google-gemini",
        model_name="gemini-2.0-flash",
        prompt_version="v1.0",
        schema_version="v1.0",
        status="COMPLETED",
        summary="Test incident investigation grounded in telemetry evidence.",
        investigation_json={"incident_summary": "Test summary", "timeline": []},
        evidence_hash="hash_abc_123",
        prompt_tokens=450,
        completion_tokens=220,
        total_tokens=670,
        latency_ms=1250,
        error_message=None,
    )
    db_session.add(inv)
    db_session.commit()
    db_session.refresh(inv)

    assert inv.id is not None
    assert inv.correlation_group_id == group.id
    assert inv.provider == "google-gemini"
    assert inv.prompt_tokens == 450
    assert inv.investigation_json["incident_summary"] == "Test summary"

    # Delete correlation group -> Foreign key SET NULL ensures investigation is NOT deleted!
    db_session.delete(group)
    db_session.commit()

    # Refresh investigation from DB
    db_session.refresh(inv)
    assert inv.id is not None
    assert inv.correlation_group_id is None  # Preserved audit record!
