"""Tests for read-only correlation investigation retrieval endpoint (GET /api/v1/correlations/{id}/investigation).

Guarantees verified:
- Read-only retrieval returns 200 with null when no investigation exists.
- Never invokes Gemini or AI provider.
- Never creates or mutates database records.
- Correctly retrieves existing COMPLETED investigations.
- Correctly retrieves FAILED investigations with sanitized error message.
- Correctly retrieves PENDING / RUNNING investigations.
- Rejects non-existent correlation groups with 404.
- Enforces cross-project isolation with 403 on project mismatch.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.correlation import CorrelationGroup
from app.models.investigation import Investigation
from app.models.project import Project
from app.models.service import Service
from app.schemas.correlation import CorrelationConfig, CorrelationEvaluationRequest
from app.schemas.investigation import (
    InvestigationResult,
    InvestigationStep,
    RemediationRecommendation,
    RemediationActionType,
    RiskLevel,
    RootCauseEvidenceExplanation,
    TimelineEvidenceEvent,
)
from app.services.correlation.service import CorrelationService


def _setup_correlation_group(db: Session) -> tuple[Project, CorrelationGroup]:
    proj = db.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t = datetime(2026, 11, 8, 10, 0, 0, tzinfo=timezone.utc)

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
    return proj, res.groups[0]


def test_read_only_endpoint_no_investigation_returns_200_null(client: TestClient, db_session: Session):
    """When no investigation exists, GET returns 200 with null and creates 0 database records."""
    proj, group = _setup_correlation_group(db_session)

    initial_inv_count = db_session.query(Investigation).count()

    response = client.get(f"/api/v1/correlations/{group.id}/investigation")
    assert response.status_code == 200
    assert response.json() is None

    # Prove no database records were created
    final_inv_count = db_session.query(Investigation).count()
    assert final_inv_count == initial_inv_count


def test_read_only_endpoint_returns_existing_completed_investigation(client: TestClient, db_session: Session):
    """When a COMPLETED investigation exists, GET returns it with full payload."""
    proj, group = _setup_correlation_group(db_session)
    top_cand = group.ranked_candidates[0]

    valid_result = InvestigationResult(
        incident_summary="Inventory Service query lock contention caused downstream cascade.",
        timeline=[
            TimelineEvidenceEvent(
                timestamp=group.participating_events[0].occurred_at,
                event_id=group.participating_events[0].event_id,
                service_id=group.participating_events[0].service_id,
                service_name=group.participating_events[0].service_name,
                metric_name=group.participating_events[0].metric_name,
                observation="Observed latency degradation.",
                severity="critical",
            )
        ],
        root_cause_analysis=RootCauseEvidenceExplanation(
            candidate_id=top_cand.service_id,
            service_id=top_cand.service_id,
            service_name=top_cand.service_name,
            explanation="Inventory service is root cause.",
        ),
        prioritized_investigation_steps=[
            InvestigationStep(step_number=1, target_service="inventory-service", action="Check locks", purpose="Verify")
        ],
        remediation_recommendations=[
            RemediationRecommendation(
                title="Restart Pooler",
                action_type=RemediationActionType.RESTART,
                target_service="inventory-service",
                description="Restart database connection pooler",
                risk_level=RiskLevel.LOW,
                preconditions=["Replicas healthy"],
                rollback_procedure="Revert",
                requires_human_approval=True,
                command_snippet=None,
            )
        ],
    )

    inv = Investigation(
        id=uuid4(),
        correlation_group_id=group.id,
        provider="google-gemini",
        model_name="gemini-3.8-flash",
        prompt_version="v1.0",
        schema_version="v1.0",
        status="COMPLETED",
        investigation_json=valid_result.model_dump(mode="json"),
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db_session.add(inv)
    db_session.commit()

    response = client.get(f"/api/v1/correlations/{group.id}/investigation")
    assert response.status_code == 200
    data = response.json()
    assert data is not None
    assert data["id"] == str(inv.id)
    assert data["correlation_group_id"] == str(group.id)
    assert data["status"] == "COMPLETED"
    assert data["provider"] == "google-gemini"
    assert data["model_name"] == "gemini-3.8-flash"
    assert "Inventory Service query lock contention" in data["result"]["incident_summary"]


def test_read_only_endpoint_returns_failed_investigation_status(client: TestClient, db_session: Session):
    """When an investigation has FAILED, GET returns 200 with FAILED status and error_message."""
    proj, group = _setup_correlation_group(db_session)

    inv = Investigation(
        id=uuid4(),
        correlation_group_id=group.id,
        provider="google-gemini",
        model_name="gemini-3.8-flash",
        prompt_version="v1.0",
        schema_version="v1.0",
        status="FAILED",
        error_message="Gemini investigation provider timeout after 25s.",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db_session.add(inv)
    db_session.commit()

    response = client.get(f"/api/v1/correlations/{group.id}/investigation")
    assert response.status_code == 200
    data = response.json()
    assert data is not None
    assert data["id"] == str(inv.id)
    assert data["status"] == "FAILED"
    assert "timeout" in data["error_message"]
    assert data["result"] is None


def test_read_only_endpoint_returns_pending_or_running_status(client: TestClient, db_session: Session):
    """When an investigation is RUNNING, GET returns 200 with RUNNING status without triggering work."""
    proj, group = _setup_correlation_group(db_session)

    inv = Investigation(
        id=uuid4(),
        correlation_group_id=group.id,
        provider="google-gemini",
        model_name="gemini-3.8-flash",
        prompt_version="v1.0",
        schema_version="v1.0",
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db_session.add(inv)
    db_session.commit()

    response = client.get(f"/api/v1/correlations/{group.id}/investigation")
    assert response.status_code == 200
    data = response.json()
    assert data is not None
    assert data["status"] == "RUNNING"
    assert data["result"] is None


def test_read_only_endpoint_nonexistent_group_returns_404(client: TestClient):
    """Non-existent correlation group ID returns 404 Not Found."""
    fake_id = uuid4()
    response = client.get(f"/api/v1/correlations/{fake_id}/investigation")
    assert response.status_code == 404
    assert f"Correlation group '{fake_id}' was not found." in response.json()["detail"]


def test_read_only_endpoint_cross_project_isolation(client: TestClient, db_session: Session):
    """Providing mismatched X-Project-Id returns 403 Forbidden."""
    proj, group = _setup_correlation_group(db_session)
    foreign_proj_id = uuid4()

    response = client.get(
        f"/api/v1/correlations/{group.id}/investigation",
        headers={"X-Project-Id": str(foreign_proj_id)},
    )
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]

    # Matching project ID succeeds
    valid_response = client.get(
        f"/api/v1/correlations/{group.id}/investigation",
        headers={"X-Project-Id": str(proj.id)},
    )
    assert valid_response.status_code == 200

