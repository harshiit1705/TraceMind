"""Comprehensive hermetic test suite for Sprint 5.2: Gemini investigation pipeline, lifecycle, safety, and API."""

from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.correlation import CorrelationGroup
from app.models.investigation import Investigation
from app.models.project import Project
from app.models.service import Service
from app.schemas.correlation import CorrelationConfig, CorrelationEvaluationRequest
from app.schemas.investigation import (
    EvidencePackage,
    EvidenceReference,
    InvestigationGenerateRequest,
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
from app.services.investigation.gemini_provider import GeminiInvestigationProvider
from app.services.investigation.provider import (
    InvestigationProvider,
    InvestigationProviderResult,
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
from app.services.investigation.validator import (
    GroundingValidationError,
    validate_investigation_result_against_evidence,
)


# --- 1. Mock Investigation Provider for Hermetic Testing ---

class MockInvestigationProvider(InvestigationProvider):
    """Deterministic mock provider simulating Gemini responses without requiring live API keys or network access."""

    def __init__(
        self,
        mode: str = "success",
        custom_result: Optional[InvestigationResult] = None,
        prompt_tokens: int = 512,
        completion_tokens: int = 256,
        latency_ms: int = 420,
    ):
        self.mode = mode
        self.custom_result = custom_result
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.latency_ms = latency_ms
        self.call_count = 0
        self.closed = False
        self.provider_name = "mock-gemini"
        self.model_name = "gemini-3.8-flash"

    async def aclose(self) -> None:
        self.closed = True

    async def generate_investigation(
        self,
        evidence: EvidencePackage,
    ) -> InvestigationProviderResult:
        self.call_count += 1

        if self.custom_result is not None:
            return InvestigationProviderResult(
                result=self.custom_result,
                provider="mock-gemini",
                model_name=self.model_name,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_tokens=self.prompt_tokens + self.completion_tokens,
                latency_ms=self.latency_ms,
            )

        if self.mode == "timeout":
            raise ProviderTimeoutError("Gemini investigation request timed out after 25s.")
        elif self.mode == "config_error":
            raise ProviderConfigError("Gemini API key is not configured.")
        elif self.mode == "transient_error":
            raise ProviderTransientError("Gemini API returned error code 503: Service Unavailable.")
        elif self.mode == "permanent_error":
            raise ProviderPermanentError("Gemini output failed schema validation: Invalid JSON format.")
        elif self.mode == "hallucinated_event":
            # Synthesize result with foreign event_id to test grounding guard
            fake_event_id = uuid4()
            top_cand = evidence.ranked_candidates[0] if evidence.ranked_candidates else None
            return InvestigationProviderResult(
                result=InvestigationResult(
                    incident_summary="Hallucinated incident summary referencing a foreign telemetry event.",
                    timeline=[
                        TimelineEvidenceEvent(
                            timestamp=evidence.time_window_start,
                            event_id=fake_event_id,
                            service_id=top_cand.service_id if top_cand else uuid4(),
                            service_name="Inventory Service",
                            metric_name="latency",
                            observation="Hallucinated event spike.",
                            severity="critical",
                        )
                    ],
                    root_cause_analysis=RootCauseEvidenceExplanation(
                        candidate_id=top_cand.candidate_id if top_cand else uuid4(),
                        service_id=top_cand.service_id if top_cand else uuid4(),
                        service_name="Inventory Service",
                        explanation="Citing candidate with hallucinated event.",
                    ),
                ),
                provider="mock-gemini",
                model_name=self.model_name,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_tokens=self.prompt_tokens + self.completion_tokens,
                latency_ms=self.latency_ms,
            )

        # Mode == "success": Generate fully grounded valid result
        ev1 = evidence.participating_events[0]
        ev2 = evidence.participating_events[1] if len(evidence.participating_events) > 1 else ev1
        top_cand = evidence.ranked_candidates[0]

        valid_result = InvestigationResult(
            incident_summary="Inventory Service experienced latency degradation which cascaded downstream to Order Service within 20s.",
            timeline=[
                TimelineEvidenceEvent(
                    timestamp=ev1.occurred_at,
                    event_id=ev1.event_id,
                    service_id=ev1.service_id,
                    service_name=ev1.service_name,
                    metric_name=ev1.metric_name,
                    observation=f"Observed {ev1.metric_name} spiked to {ev1.observed_value} (+{ev1.deviation_pct:.0f}% above baseline).",
                    severity=ev1.severity,
                ),
                TimelineEvidenceEvent(
                    timestamp=ev2.occurred_at,
                    event_id=ev2.event_id,
                    service_id=ev2.service_id,
                    service_name=ev2.service_name,
                    metric_name=ev2.metric_name,
                    observation=f"Observed {ev2.metric_name} degraded to {ev2.observed_value} (+{ev2.deviation_pct:.0f}% above baseline).",
                    severity=ev2.severity,
                ),
            ],
            root_cause_analysis=RootCauseEvidenceExplanation(
                candidate_id=top_cand.candidate_id,
                service_id=top_cand.service_id,
                service_name=top_cand.service_name,
                explanation=f"{top_cand.service_name} initiated the cascading failure as upstream dependency.",
                contributing_factors=["Downstream service lacks circuit-breaking protection."],
            ),
            evidence_references=[
                EvidenceReference(
                    source_record_type="anomaly_event",
                    source_id=ev1.event_id,
                    supported_field="observed_value",
                    summary_citation=f"Observed latency of {ev1.observed_value}ms on {ev1.service_name}",
                )
            ],
            uncertainties_and_gaps=[
                UncertaintyGap(
                    category="missing_telemetry",
                    description="Raw application logs and trace spans are uninstrumented.",
                    impact_on_confidence="Moderate",
                )
            ],
            prioritized_investigation_steps=[
                InvestigationStep(
                    step_number=1,
                    target_service=ev1.service_name,
                    action="Inspect connection pool utilization",
                    purpose="Confirm if pool exhaustion caused latency queueing",
                )
            ],
            remediation_recommendations=[
                RemediationRecommendation(
                    title="Scale Inventory Service Replicas",
                    action_type=RemediationActionType.SCALING,
                    target_service=ev1.service_name,
                    description="Temporarily increase replica count from 2 to 4 to drain queued requests.",
                    risk_level=RiskLevel.LOW,
                    preconditions=["Check cluster compute headroom"],
                    rollback_procedure="Scale replicas back to 2",
                    requires_human_approval=True,
                    command_snippet=None,
                )
            ],
        )

        return InvestigationProviderResult(
            result=valid_result,
            provider="mock-gemini",
            model_name=self.model_name,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.prompt_tokens + self.completion_tokens,
            latency_ms=self.latency_ms,
        )


# --- 2. Helper fixture to create a real persisted CorrelationGroup ---

def _setup_test_correlation_group(db: Session) -> tuple[Project, CorrelationGroup]:
    proj = db.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

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
    db.add(bl)

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
    db.add_all([ev1, ev2])
    db.commit()

    corr_svc = CorrelationService(db)
    res = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=proj.id,
            start_time=t - timedelta(minutes=1),
            end_time=t + timedelta(minutes=1),
            config=CorrelationConfig(min_events_per_group=2),
        )
    )
    assert res.correlation_groups_count >= 1
    return proj, res.groups[0]


# --- 3. Configuration & Provider Unit Tests ---

def test_gemini_configuration_default_model():
    """Verify Gemini default model is configured to gemini-3.8-flash."""
    assert settings.GEMINI_MODEL == "gemini-3.8-flash"
    assert settings.GEMINI_TIMEOUT_SECONDS == 25


def test_gemini_provider_unconfigured_fails_safely():
    """GeminiInvestigationProvider without configured API key raises ProviderConfigError."""
    provider = GeminiInvestigationProvider(api_key="")
    assert not provider.is_configured()

    with pytest.raises(ProviderConfigError, match="Gemini API key is not configured"):
        import asyncio
        evidence = EvidencePackage(
            package_version="1.0",
            correlation_group_id=uuid4(),
            project_id=uuid4(),
            project_slug="test",
            project_name="Test",
            time_window_start=datetime.now(timezone.utc),
            time_window_end=datetime.now(timezone.utc),
            confidence_score=1.0,
            topology_complete=True,
            topology_status_explanation="",
            participating_events=[],
            service_dependencies=[],
            ranked_candidates=[],
            evidence_hash="abc",
        )
        asyncio.run(provider.generate_investigation(evidence))


@pytest.mark.asyncio
async def test_mock_provider_success():
    """Mock provider returns structured result and accurate token/latency metadata."""
    provider = MockInvestigationProvider(mode="success", prompt_tokens=300, completion_tokens=150, latency_ms=250)
    ev_id = uuid4()
    cand_id = uuid4()
    svc_id = uuid4()
    now = datetime.now(timezone.utc)
    evidence = EvidencePackage(
        package_version="1.0",
        correlation_group_id=uuid4(),
        project_id=uuid4(),
        project_slug="test",
        project_name="Test",
        time_window_start=now,
        time_window_end=now + timedelta(minutes=5),
        confidence_score=0.9,
        topology_complete=True,
        topology_status_explanation="DAG complete",
        participating_events=[
            {
                "event_id": ev_id,
                "service_id": svc_id,
                "service_name": "Inventory",
                "service_identifier": "svc:inv",
                "metric_name": "latency",
                "observed_value": 450.0,
                "expected_baseline": 45.0,
                "deviation_pct": 900.0,
                "severity": "critical",
                "detection_method": "rolling_average",
                "occurred_at": now,
                "relevance_score": 1.0,
                "correlation_reason": "High latency deviation",
            }
        ],
        service_dependencies=[],
        ranked_candidates=[
            {
                "candidate_id": cand_id,
                "service_id": svc_id,
                "service_name": "Inventory",
                "service_identifier": "svc:inv",
                "rank": 1,
                "score": 0.95,
                "confidence": "HIGH",
                "is_probable_root_cause": True,
                "temporal_precedence_score": 1.0,
                "topological_score": 1.0,
                "blast_radius_score": 0.8,
                "severity_score": 1.0,
            }
        ],
        evidence_hash="fake_hash_123",
    )

    res = await provider.generate_investigation(evidence)
    assert res.provider == "mock-gemini"
    assert res.prompt_tokens == 300
    assert res.completion_tokens == 150
    assert res.total_tokens == 450
    assert res.latency_ms == 250
    assert res.result.incident_summary != ""


# --- 4. Investigation Lifecycle Tests ---

@pytest.mark.asyncio
async def test_investigation_lifecycle_success(db_session: Session):
    """Full lifecycle: PENDING -> RUNNING -> COMPLETED with valid timestamps and grounding."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="success")
    service = InvestigationService(db_session, provider=provider)

    inv = await service.get_or_create_investigation(
        correlation_group_id=group.id,
        project_id=proj.id,
    )

    assert inv.id is not None
    assert inv.correlation_group_id == group.id
    assert inv.status == "COMPLETED"
    assert inv.provider == "mock-gemini"
    assert inv.model_name == "gemini-3.8-flash"
    assert inv.prompt_version == "v1.0"
    assert inv.schema_version == "v1.0"

    # Started_at must be valid UTC timestamp (satisfies NOT NULL constraint)
    assert inv.started_at is not None
    assert inv.completed_at is not None
    assert inv.completed_at >= inv.started_at

    # Metadata and payload persisted
    assert inv.evidence_hash is not None
    assert len(inv.evidence_hash) == 64
    assert inv.prompt_tokens == 512
    assert inv.completion_tokens == 256
    assert inv.total_tokens == 768
    assert inv.latency_ms == 420
    assert inv.investigation_json is not None
    assert "incident_summary" in inv.investigation_json
    assert len(inv.investigation_json["timeline"]) == 2
    assert inv.investigation_json["remediation_recommendations"][0]["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_investigation_idempotency_reuses_completed(db_session: Session):
    """Calling get_or_create_investigation repeatedly reuses existing COMPLETED investigation without re-calling provider."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="success")
    service = InvestigationService(db_session, provider=provider)

    inv1 = await service.get_or_create_investigation(group.id, proj.id)
    assert provider.call_count == 1

    inv2 = await service.get_or_create_investigation(group.id, proj.id)
    assert provider.call_count == 1  # Reused!
    assert inv1.id == inv2.id


@pytest.mark.asyncio
async def test_investigation_force_regenerate(db_session: Session):
    """Passing force_regenerate=True generates a fresh investigation."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="success")
    service = InvestigationService(db_session, provider=provider)

    inv1 = await service.get_or_create_investigation(group.id, proj.id)
    assert provider.call_count == 1

    inv2 = await service.get_or_create_investigation(group.id, proj.id, force_regenerate=True)
    assert provider.call_count == 2
    assert inv1.id != inv2.id
    assert inv2.status == "COMPLETED"


@pytest.mark.asyncio
async def test_investigation_project_isolation_enforcement(db_session: Session):
    """Requesting an investigation for a group with a mismatched project_id fails closed."""
    proj, group = _setup_test_correlation_group(db_session)
    wrong_project_id = uuid4()
    provider = MockInvestigationProvider(mode="success")
    service = InvestigationService(db_session, provider=provider)

    with pytest.raises(ProjectIsolationError, match="Access denied"):
        await service.get_or_create_investigation(group.id, wrong_project_id)


@pytest.mark.asyncio
async def test_investigation_nonexistent_group_raises_404(db_session: Session):
    """Requesting an investigation for a nonexistent correlation group raises CorrelationGroupNotFoundError."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    fake_group_id = uuid4()
    provider = MockInvestigationProvider(mode="success")
    service = InvestigationService(db_session, provider=provider)

    with pytest.raises(CorrelationGroupNotFoundError, match="was not found"):
        await service.get_or_create_investigation(fake_group_id, proj.id)


@pytest.mark.asyncio
async def test_investigation_provider_failure_persists_failed_status(db_session: Session):
    """When the provider raises an exception, the investigation record is persisted as FAILED with a sanitized error."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="timeout")
    service = InvestigationService(db_session, provider=provider)

    with pytest.raises(ProviderTimeoutError):
        await service.get_or_create_investigation(group.id, proj.id)

    # Verify database record is marked FAILED, not left PENDING or RUNNING
    failed_inv = (
        db_session.query(Investigation)
        .filter(Investigation.correlation_group_id == group.id)
        .first()
    )
    assert failed_inv is not None
    assert failed_inv.status == "FAILED"
    assert "timed out" in failed_inv.error_message
    assert failed_inv.completed_at is not None


@pytest.mark.asyncio
async def test_investigation_grounding_failure_persists_failed_status(db_session: Session):
    """When the provider hallucinates a foreign event_id, grounding validator rejects it and marks investigation FAILED."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="hallucinated_event")
    service = InvestigationService(db_session, provider=provider)

    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    failed_inv = (
        db_session.query(Investigation)
        .filter(Investigation.correlation_group_id == group.id)
        .first()
    )
    assert failed_inv is not None
    assert failed_inv.status == "FAILED"
    assert "Grounding validation error" in failed_inv.error_message
    assert failed_inv.investigation_json is None  # Never persisted as completed!


# --- 5. Strengthened Grounding Guard Negative Tests (Correction B) ---

def _build_valid_test_result(evidence: EvidencePackage) -> InvestigationResult:
    ev1 = evidence.participating_events[0]
    top_cand = evidence.ranked_candidates[0]
    return InvestigationResult(
        incident_summary="Grounded incident summary for unit testing.",
        timeline=[
            TimelineEvidenceEvent(
                timestamp=ev1.occurred_at,
                event_id=ev1.event_id,
                service_id=ev1.service_id,
                service_name=ev1.service_name,
                metric_name=ev1.metric_name,
                observation="Authentic metric spike observation.",
                severity=ev1.severity,
            )
        ],
        root_cause_analysis=RootCauseEvidenceExplanation(
            candidate_id=top_cand.candidate_id,
            service_id=top_cand.service_id,
            service_name=top_cand.service_name,
            explanation="Authentic root cause explanation citing valid candidate.",
        ),
        evidence_references=[
            EvidenceReference(
                source_record_type="anomaly_event",
                source_id=ev1.event_id,
                supported_field="observed_value",
                summary_citation="Authentic citation.",
            )
        ],
        remediation_recommendations=[
            RemediationRecommendation(
                title="Scale Replicas",
                action_type=RemediationActionType.SCALING,
                target_service=ev1.service_name,
                description="Scale service replicas to handle load.",
                risk_level=RiskLevel.LOW,
                preconditions=["Capacity check"],
                rollback_procedure="Scale down",
                requires_human_approval=True,
                command_snippet=None,
            )
        ],
    )


@pytest.mark.asyncio
async def test_grounding_rejects_valid_event_with_fabricated_service_id(db_session: Session):
    """Timeline event with valid event_id but fabricated service_id must fail and persist FAILED status."""
    proj, group = _setup_test_correlation_group(db_session)
    evidence = InvestigationService(db_session).evidence_builder.build_evidence_package(group.id, proj.id)
    bad_result = _build_valid_test_result(evidence)
    bad_result.timeline[0].service_id = uuid4()  # Fabricated service_id!

    with pytest.raises(GroundingValidationError, match="mismatched service_id"):
        validate_investigation_result_against_evidence(bad_result, evidence)

    # Test via service lifecycle
    provider = MockInvestigationProvider(custom_result=bad_result)
    service = InvestigationService(db_session, provider=provider)
    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    inv = db_session.query(Investigation).filter(Investigation.correlation_group_id == group.id).first()
    assert inv.status == "FAILED"
    assert "mismatched service_id" in inv.error_message


@pytest.mark.asyncio
async def test_grounding_rejects_valid_event_with_incorrect_metric_name(db_session: Session):
    """Timeline event with valid event_id but altered metric_name must fail and persist FAILED status."""
    proj, group = _setup_test_correlation_group(db_session)
    evidence = InvestigationService(db_session).evidence_builder.build_evidence_package(group.id, proj.id)
    bad_result = _build_valid_test_result(evidence)
    bad_result.timeline[0].metric_name = "hallucinated_packet_loss"  # Incorrect metric!

    with pytest.raises(GroundingValidationError, match="mismatched metric_name"):
        validate_investigation_result_against_evidence(bad_result, evidence)

    provider = MockInvestigationProvider(custom_result=bad_result)
    service = InvestigationService(db_session, provider=provider)
    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    inv = db_session.query(Investigation).filter(Investigation.correlation_group_id == group.id).first()
    assert inv.status == "FAILED"
    assert "mismatched metric_name" in inv.error_message


@pytest.mark.asyncio
async def test_grounding_rejects_valid_event_with_altered_timestamp(db_session: Session):
    """Timeline event with valid event_id but altered timestamp must fail and persist FAILED status."""
    proj, group = _setup_test_correlation_group(db_session)
    evidence = InvestigationService(db_session).evidence_builder.build_evidence_package(group.id, proj.id)
    bad_result = _build_valid_test_result(evidence)
    bad_result.timeline[0].timestamp = bad_result.timeline[0].timestamp + timedelta(hours=2)  # Altered!

    with pytest.raises(GroundingValidationError, match="timestamp was altered"):
        validate_investigation_result_against_evidence(bad_result, evidence)

    provider = MockInvestigationProvider(custom_result=bad_result)
    service = InvestigationService(db_session, provider=provider)
    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    inv = db_session.query(Investigation).filter(Investigation.correlation_group_id == group.id).first()
    assert inv.status == "FAILED"
    assert "timestamp was altered" in inv.error_message


@pytest.mark.asyncio
async def test_grounding_rejects_valid_event_with_incorrect_severity(db_session: Session):
    """Timeline event with valid event_id but altered severity must fail and persist FAILED status."""
    proj, group = _setup_test_correlation_group(db_session)
    evidence = InvestigationService(db_session).evidence_builder.build_evidence_package(group.id, proj.id)
    bad_result = _build_valid_test_result(evidence)
    bad_result.timeline[0].severity = "low"  # Altered severity (actual is critical)!

    with pytest.raises(GroundingValidationError, match="severity was altered"):
        validate_investigation_result_against_evidence(bad_result, evidence)

    provider = MockInvestigationProvider(custom_result=bad_result)
    service = InvestigationService(db_session, provider=provider)
    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    inv = db_session.query(Investigation).filter(Investigation.correlation_group_id == group.id).first()
    assert inv.status == "FAILED"
    assert "severity was altered" in inv.error_message


@pytest.mark.asyncio
async def test_grounding_rejects_fabricated_candidate_id(db_session: Session):
    """Root cause explanation referencing unknown candidate_id must fail and persist FAILED status."""
    proj, group = _setup_test_correlation_group(db_session)
    evidence = InvestigationService(db_session).evidence_builder.build_evidence_package(group.id, proj.id)
    bad_result = _build_valid_test_result(evidence)
    bad_result.root_cause_analysis.candidate_id = uuid4()  # Fabricated candidate!

    with pytest.raises(GroundingValidationError, match="does not exist among the deterministic ranked candidates"):
        validate_investigation_result_against_evidence(bad_result, evidence)

    provider = MockInvestigationProvider(custom_result=bad_result)
    service = InvestigationService(db_session, provider=provider)
    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    inv = db_session.query(Investigation).filter(Investigation.correlation_group_id == group.id).first()
    assert inv.status == "FAILED"


@pytest.mark.asyncio
async def test_grounding_rejects_candidate_with_mismatched_service_id(db_session: Session):
    """Root cause explanation referencing valid candidate but mismatched service_id must fail."""
    proj, group = _setup_test_correlation_group(db_session)
    evidence = InvestigationService(db_session).evidence_builder.build_evidence_package(group.id, proj.id)
    bad_result = _build_valid_test_result(evidence)
    bad_result.root_cause_analysis.service_id = uuid4()  # Mismatched service!

    with pytest.raises(GroundingValidationError, match="Candidate service ID mismatch"):
        validate_investigation_result_against_evidence(bad_result, evidence)

    provider = MockInvestigationProvider(custom_result=bad_result)
    service = InvestigationService(db_session, provider=provider)
    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    inv = db_session.query(Investigation).filter(Investigation.correlation_group_id == group.id).first()
    assert inv.status == "FAILED"
    assert "Candidate service ID mismatch" in inv.error_message


@pytest.mark.asyncio
async def test_grounding_rejects_valid_source_id_with_invalid_source_record_type(db_session: Session):
    """Evidence reference citing valid source_id but unsupported source_record_type must fail."""
    proj, group = _setup_test_correlation_group(db_session)
    evidence = InvestigationService(db_session).evidence_builder.build_evidence_package(group.id, proj.id)
    bad_result = _build_valid_test_result(evidence)
    bad_result.evidence_references[0].source_record_type = "unsupported_log_record"  # Invalid type!

    with pytest.raises(GroundingValidationError, match="Invalid evidence source_record_type"):
        validate_investigation_result_against_evidence(bad_result, evidence)

    provider = MockInvestigationProvider(custom_result=bad_result)
    service = InvestigationService(db_session, provider=provider)
    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    inv = db_session.query(Investigation).filter(Investigation.correlation_group_id == group.id).first()
    assert inv.status == "FAILED"
    assert "Invalid evidence source_record_type" in inv.error_message


@pytest.mark.asyncio
async def test_grounding_rejects_valid_source_id_with_unsupported_field(db_session: Session):
    """Evidence reference citing valid source_id and valid type but unsupported field must fail."""
    proj, group = _setup_test_correlation_group(db_session)
    evidence = InvestigationService(db_session).evidence_builder.build_evidence_package(group.id, proj.id)
    bad_result = _build_valid_test_result(evidence)
    bad_result.evidence_references[0].supported_field = "invented_stacktrace_dump"  # Unsupported field!

    with pytest.raises(GroundingValidationError, match="is not supported for source record type"):
        validate_investigation_result_against_evidence(bad_result, evidence)

    provider = MockInvestigationProvider(custom_result=bad_result)
    service = InvestigationService(db_session, provider=provider)
    with pytest.raises(GroundingValidationError):
        await service.get_or_create_investigation(group.id, proj.id)

    inv = db_session.query(Investigation).filter(Investigation.correlation_group_id == group.id).first()
    assert inv.status == "FAILED"
    assert "is not supported for source record type" in inv.error_message


# --- 6. Provider Error Handling & Client Lifecycle Tests (Corrections C & D) ---

@pytest.mark.asyncio
async def test_gemini_client_lifecycle_aclose_called(db_session: Session):
    """Verify provider.aclose() is invoked upon completion and failure by InvestigationService."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="success")
    service = InvestigationService(db_session, provider=provider)

    await service.get_or_create_investigation(group.id, proj.id)
    assert provider.closed is True

    # Test that aclose() is also invoked on failure
    fail_provider = MockInvestigationProvider(mode="timeout")
    fail_service = InvestigationService(db_session, provider=fail_provider)
    with pytest.raises(ProviderTimeoutError):
        await fail_service.get_or_create_investigation(group.id, proj.id, force_regenerate=True)
    assert fail_provider.closed is True


def test_api_provider_transient_error_returns_503(client: TestClient, db_session: Session):
    """When provider raises ProviderTransientError (e.g. rate limit), API returns HTTP 503."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="transient_error")
    from app.services.investigation.service import InvestigationService
    orig_init = InvestigationService.__init__

    def patched_init(self, db, provider_arg=None):
        orig_init(self, db, provider=provider)

    InvestigationService.__init__ = patched_init
    try:
        response = client.post(
            "/api/v1/investigations/generate",
            json={"correlation_group_id": str(group.id)},
        )
        assert response.status_code == 503
        assert "temporarily unavailable" in response.json()["detail"]
    finally:
        InvestigationService.__init__ = orig_init


def test_api_provider_timeout_returns_504(client: TestClient, db_session: Session):
    """When provider raises ProviderTimeoutError, API returns HTTP 504 Gateway Timeout."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="timeout")
    from app.services.investigation.service import InvestigationService
    orig_init = InvestigationService.__init__

    def patched_init(self, db, provider_arg=None):
        orig_init(self, db, provider=provider)

    InvestigationService.__init__ = patched_init
    try:
        response = client.post(
            "/api/v1/investigations/generate",
            json={"correlation_group_id": str(group.id)},
        )
        assert response.status_code == 504
        assert "timed out" in response.json()["detail"]
    finally:
        InvestigationService.__init__ = orig_init


def test_api_provider_permanent_error_returns_422(client: TestClient, db_session: Session):
    """When provider raises ProviderPermanentError (e.g. malformed output), API returns HTTP 422."""
    proj, group = _setup_test_correlation_group(db_session)
    provider = MockInvestigationProvider(mode="permanent_error")
    from app.services.investigation.service import InvestigationService
    orig_init = InvestigationService.__init__

    def patched_init(self, db, provider_arg=None):
        orig_init(self, db, provider=provider)

    InvestigationService.__init__ = patched_init
    try:
        response = client.post(
            "/api/v1/investigations/generate",
            json={"correlation_group_id": str(group.id)},
        )
        assert response.status_code == 422
        assert "validation failure" in response.json()["detail"].lower()
    finally:
        InvestigationService.__init__ = orig_init


# --- 7. Standard API Endpoint Tests ---

def test_api_generate_investigation_success(client: TestClient, db_session: Session):
    """POST /api/v1/investigations/generate creates or returns grounded investigation."""
    from app.services.investigation.service import InvestigationService
    proj, group = _setup_test_correlation_group(db_session)

    mock_provider = MockInvestigationProvider(mode="success")
    orig_init = InvestigationService.__init__

    def patched_init(self, db, provider=None):
        orig_init(self, db, provider=provider or mock_provider)

    InvestigationService.__init__ = patched_init
    try:
        response = client.post(
            "/api/v1/investigations/generate",
            json={"correlation_group_id": str(group.id), "force_regenerate": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["correlation_group_id"] == str(group.id)
        assert data["status"] == "COMPLETED"
        assert data["provider"] == "mock-gemini"
        assert data["result"] is not None
        assert "timeline" in data["result"]
        assert len(data["result"]["timeline"]) == 2

        inv_id = data["id"]

        # GET /api/v1/investigations/{id}
        get_resp = client.get(f"/api/v1/investigations/{inv_id}")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["id"] == inv_id
        assert get_data["status"] == "COMPLETED"
    finally:
        InvestigationService.__init__ = orig_init


def test_api_generate_investigation_cross_project_header_rejected(client: TestClient, db_session: Session):
    """POST /api/v1/investigations/generate with mismatched X-Project-Id header returns 403."""
    proj, group = _setup_test_correlation_group(db_session)
    foreign_project_id = uuid4()

    response = client.post(
        "/api/v1/investigations/generate",
        json={"correlation_group_id": str(group.id)},
        headers={"X-Project-Id": str(foreign_project_id)},
    )
    assert response.status_code == 403
    assert "belongs to a different project" in response.json()["detail"]


def test_api_generate_nonexistent_group_returns_404(client: TestClient):
    """POST /api/v1/investigations/generate with nonexistent correlation_group_id returns 404."""
    fake_group_id = uuid4()
    response = client.post(
        "/api/v1/investigations/generate",
        json={"correlation_group_id": str(fake_group_id)},
    )
    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]


def test_api_generate_rejects_client_model_tampering(client: TestClient):
    """POST /api/v1/investigations/generate rejects extra client-supplied fields like model_name or provider."""
    fake_group_id = uuid4()
    response = client.post(
        "/api/v1/investigations/generate",
        json={
            "correlation_group_id": str(fake_group_id),
            "model_name": "malicious-model-override",  # Forbidden extra field!
        },
    )
    assert response.status_code == 422


def test_api_unconfigured_gemini_returns_503(client: TestClient, db_session: Session):
    """POST /api/v1/investigations/generate with unconfigured Gemini provider returns 503 Service Unavailable."""
    proj, group = _setup_test_correlation_group(db_session)

    unconfigured_provider = GeminiInvestigationProvider(api_key="")
    from app.services.investigation.service import InvestigationService
    orig_init = InvestigationService.__init__

    def patched_init(self, db, provider=None):
        orig_init(self, db, provider=unconfigured_provider)

    InvestigationService.__init__ = patched_init
    try:
        response = client.post(
            "/api/v1/investigations/generate",
            json={"correlation_group_id": str(group.id)},
        )
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]
    finally:
        InvestigationService.__init__ = orig_init


def test_legacy_demo_investigation_not_represented_as_grounded_gemini(client: TestClient, db_session: Session):
    """Legacy demo incident investigations cannot be represented as actual grounded Gemini investigations."""
    from app.services.incident_service import IncidentService
    svc = IncidentService(db_session)
    legacy_inv = svc.get_investigation_for_incident("INC-8492")
    assert legacy_inv is not None

    response = client.get(f"/api/v1/investigations/{legacy_inv.id}")
    assert response.status_code == 200
    data = response.json()

    # Legacy demo response contract
    assert data["id"] == str(legacy_inv.id)
    assert data["is_demo"] is True
    assert data["agent_name"] == "Autonomous Agent #4"
    assert "findings" in data
    assert "recommendations" in data

    # Must NOT have correlation-grounded Gemini fields
    assert "result" not in data or data.get("result") is None
    assert data.get("correlation_group_id") is None


def test_two_sequential_investigation_requests_using_same_app(client: TestClient, db_session: Session):
    """Test two sequential investigation requests using the same FastAPI app client instance."""
    from app.services.investigation.service import InvestigationService
    proj, group1 = _setup_test_correlation_group(db_session)

    # Setup a second distinct correlation group in the same project
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    t = datetime(2026, 11, 7, 13, 0, 0, tzinfo=timezone.utc)
    ev3 = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=inv_svc.id,
        metric_name="latency",
        observed_value=600.0,
        expected_baseline=45.0,
        deviation_pct=1200.0,
        severity="critical",
        detection_method="rolling_average",
        occurred_at=t,
        status="open",
    )
    db_session.add(ev3)
    db_session.commit()

    corr_svc = CorrelationService(db_session)
    res2 = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=proj.id,
            start_time=t - timedelta(minutes=1),
            end_time=t + timedelta(minutes=1),
            config=CorrelationConfig(min_events_per_group=1),
        )
    )
    group2 = res2.groups[0]

    mock_provider = MockInvestigationProvider(mode="success")
    orig_init = InvestigationService.__init__

    def patched_init(self, db, provider=None):
        orig_init(self, db, provider=provider or mock_provider)

    InvestigationService.__init__ = patched_init
    try:
        # Request 1
        resp1 = client.post(
            "/api/v1/investigations/generate",
            json={"correlation_group_id": str(group1.id)},
        )
        assert resp1.status_code == 200
        assert resp1.json()["correlation_group_id"] == str(group1.id)
        assert resp1.json()["status"] == "COMPLETED"

        # Request 2 (sequential on same application instance)
        resp2 = client.post(
            "/api/v1/investigations/generate",
            json={"correlation_group_id": str(group2.id)},
        )
        assert resp2.status_code == 200
        assert resp2.json()["correlation_group_id"] == str(group2.id)
        assert resp2.json()["status"] == "COMPLETED"

    finally:
        InvestigationService.__init__ = orig_init


@pytest.mark.asyncio
async def test_provider_aclose_does_not_break_subsequent_request():
    """Ensure closing GeminiInvestigationProvider after one request cannot break the next."""
    provider = GeminiInvestigationProvider(api_key="mock_test_api_key_12345")
    assert provider.is_configured()

    # First access initializes client
    client1 = provider._get_client()
    assert client1 is not None

    # Closing client releases resources and resets _client reference to None
    await provider.aclose()
    assert provider._client is None

    # Next request lazily recreates client without throwing closed-client RuntimeError
    client2 = provider._get_client()
    assert client2 is not None
    assert client2 is not client1

    await provider.aclose()
    assert provider._client is None

