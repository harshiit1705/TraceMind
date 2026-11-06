"""Integration and API test suite for correlation evaluation, listing, and persistence endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyEvent
from app.models.correlation import CorrelationGroup
from app.models.project import Project
from app.models.service import Service


def test_evaluate_correlations_api(client: TestClient, db_session: Session):
    """Test POST /api/v1/correlations/evaluate with dependent anomaly events."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t0 = datetime(2026, 11, 6, 16, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 6, 16, 1, 0, tzinfo=timezone.utc)

    # Insert 2 dependent anomalies
    ev1 = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=inv_svc.id,
        metric_name="latency",
        observed_value=500.0,
        expected_baseline=50.0,
        deviation_pct=900.0,
        severity="critical",
        detection_method="rolling_average",
        occurred_at=t0,
        status="open",
        explanation="Inventory latency spike",
    )
    ev2 = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=order_svc.id,
        metric_name="latency",
        observed_value=900.0,
        expected_baseline=90.0,
        deviation_pct=900.0,
        severity="critical",
        detection_method="rolling_average",
        occurred_at=t1,
        status="open",
        explanation="Order latency spike",
    )
    db_session.add_all([ev1, ev2])
    db_session.commit()

    # Call evaluation API
    payload = {
        "project_id": str(proj.id),
        "start_time": (t0 - timedelta(minutes=2)).isoformat(),
        "end_time": (t1 + timedelta(minutes=2)).isoformat(),
    }
    resp = client.post("/api/v1/correlations/evaluate", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["project_id"] == str(proj.id)
    assert data["correlation_groups_count"] == 1
    assert data["total_anomalies_evaluated"] == 2

    group = data["groups"][0]
    group_id = group["id"]
    assert group["events_count"] == 2
    assert len(group["ranked_candidates"]) == 2
    assert group["ranked_candidates"][0]["service_slug"] == "inventory-service"
    assert group["ranked_candidates"][0]["is_probable_root_cause"] is True

    # Verify repeated evaluation is idempotent (duplicate prevention)
    resp2 = client.post("/api/v1/correlations/evaluate", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["correlation_groups_count"] == 1
    assert data2["groups"][0]["id"] == group_id  # Reused existing record

    # Verify database has exactly 1 CorrelationGroup
    db_groups = db_session.query(CorrelationGroup).filter_by(project_id=proj.id).all()
    assert len(db_groups) == 1

    # List groups endpoint
    list_resp = client.get(f"/api/v1/correlations?project_id={proj.id}")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # Get specific group endpoint
    get_resp = client.get(f"/api/v1/correlations/{group_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == group_id

    # Get ranked candidates endpoint
    cands_resp = client.get(f"/api/v1/correlations/{group_id}/candidates")
    assert cands_resp.status_code == 200
    cands = cands_resp.json()
    assert len(cands) == 2
    assert cands[0]["rank"] == 1


def test_empty_anomaly_window_returns_zero_groups(client: TestClient, db_session: Session):
    """When no anomaly events exist in the time window, evaluate returns 0 groups cleanly."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()

    payload = {
        "project_id": str(proj.id),
        "start_time": datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc).isoformat(),
        "end_time": datetime(2020, 1, 1, 0, 5, 0, tzinfo=timezone.utc).isoformat(),
    }
    resp = client.post("/api/v1/correlations/evaluate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlation_groups_count"] == 0
    assert data["groups"] == []


def test_invalid_time_window_rejected(client: TestClient, db_session: Session):
    """start_time after end_time must be rejected with 422."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()

    payload = {
        "project_id": str(proj.id),
        "start_time": datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
        "end_time": datetime(2026, 11, 6, 11, 0, 0, tzinfo=timezone.utc).isoformat(),
    }
    resp = client.post("/api/v1/correlations/evaluate", json=payload)
    assert resp.status_code == 422
    assert "start_time" in resp.json()["detail"].lower()


def test_nonexistent_project_returns_404(client: TestClient):
    """Evaluating or listing correlations for a nonexistent project returns 404."""
    fake_proj = str(uuid4())
    payload = {"project_id": fake_proj}
    resp = client.post("/api/v1/correlations/evaluate", json=payload)
    assert resp.status_code == 404

    list_resp = client.get(f"/api/v1/correlations?project_id={fake_proj}")
    assert list_resp.status_code == 404


def test_nonexistent_correlation_returns_404(client: TestClient):
    """Querying an unknown correlation group ID returns 404."""
    resp = client.get(f"/api/v1/correlations/{uuid4()}")
    assert resp.status_code == 404


def test_persistence_failure_rollback(client: TestClient, db_session: Session):
    """If database persistence encounters an error, transaction must rollback safely without dangling rows."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t = datetime(2026, 11, 6, 17, 0, 0, tzinfo=timezone.utc)
    ev1 = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=inv_svc.id,
        metric_name="latency",
        observed_value=200.0,
        expected_baseline=20.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t,
        status="open",
    )
    ev2 = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=order_svc.id,
        metric_name="latency",
        observed_value=300.0,
        expected_baseline=30.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t + timedelta(seconds=30),
        status="open",
    )
    db_session.add_all([ev1, ev2])
    db_session.commit()

    # Simulate a database error during commit in CorrelationRepository
    with patch("app.repositories.correlation_repository.CorrelationRepository.persist_group", side_effect=RuntimeError("Simulated DB Disk Failure")):
        payload = {
            "project_id": str(proj.id),
            "start_time": (t - timedelta(minutes=1)).isoformat(),
            "end_time": (t + timedelta(minutes=2)).isoformat(),
        }
        with pytest.raises(RuntimeError, match="Simulated DB Disk Failure"):
            from app.schemas.correlation import CorrelationEvaluationRequest
            from app.services.correlation.service import CorrelationService
            svc = CorrelationService(db_session)
            svc.evaluate_and_persist(CorrelationEvaluationRequest(**payload))

    # Verify no dangling CorrelationGroup was committed
    count = db_session.query(CorrelationGroup).filter_by(project_id=proj.id).count()
    assert count == 0


def test_overlapping_correlation_groups_lifecycle_and_idempotency(client: TestClient, db_session: Session):
    """Verify lifecycle transitions:
    - Evaluation A {A, B} -> Group 1 ACTIVE
    - Evaluation B {A, B, C} -> Group 1 SUPERSEDED, Group 2 ACTIVE
    - Evaluation C {B, C} -> Subsumed, returns encompassing Group 2 ACTIVE
    - Evaluation D {D, E} -> Disjoint, creates Group 3 ACTIVE
    """
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()
    pay_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="payment-service").first()

    # Disjoint services
    recs_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="recommendation-engine").first()
    search_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="search-indexer").first()

    t = datetime(2026, 11, 6, 21, 0, 0, tzinfo=timezone.utc)

    # Event A (Inventory) at t+0
    ev_a = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=inv_svc.id,
        metric_name="latency",
        observed_value=500.0,
        expected_baseline=50.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t,
        status="open",
    )
    # Event B (Order) at t+30s
    ev_b = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=order_svc.id,
        metric_name="latency",
        observed_value=800.0,
        expected_baseline=80.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t + timedelta(seconds=30),
        status="open",
    )
    db_session.add_all([ev_a, ev_b])
    db_session.commit()

    # --- Step 1: Evaluation A with {A, B} ---
    payload_a = {
        "project_id": str(proj.id),
        "start_time": (t - timedelta(minutes=1)).isoformat(),
        "end_time": (t + timedelta(seconds=45)).isoformat(),
    }
    resp_a = client.post("/api/v1/correlations/evaluate", json=payload_a)
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert data_a["correlation_groups_count"] == 1
    group_1_id = data_a["groups"][0]["id"]
    assert data_a["groups"][0]["status"] == "ACTIVE"
    assert data_a["groups"][0]["events_count"] == 2

    # Verify Group 1 is in DB as ACTIVE
    g1_db = db_session.query(CorrelationGroup).filter_by(id=UUID(group_1_id)).first()
    assert g1_db.status == "ACTIVE"

    # --- Step 2: Anomaly Event C (Payment) appears at t+60s ---
    ev_c = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=pay_svc.id,
        metric_name="error_rate",
        observed_value=15.0,
        expected_baseline=0.5,
        deviation_pct=2900.0,
        severity="critical",
        detection_method="rolling_average",
        occurred_at=t + timedelta(seconds=60),
        status="open",
    )
    db_session.add(ev_c)
    db_session.commit()

    # Evaluation B with broader window containing {A, B, C}
    payload_b = {
        "project_id": str(proj.id),
        "start_time": (t - timedelta(minutes=1)).isoformat(),
        "end_time": (t + timedelta(seconds=90)).isoformat(),
    }
    resp_b = client.post("/api/v1/correlations/evaluate", json=payload_b)
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["correlation_groups_count"] == 1
    group_2_id = data_b["groups"][0]["id"]
    assert group_2_id != group_1_id
    assert data_b["groups"][0]["status"] == "ACTIVE"
    assert data_b["groups"][0]["events_count"] == 3

    # Group 1 must now be marked SUPERSEDED in the database
    db_session.refresh(g1_db)
    assert g1_db.status == "SUPERSEDED"

    # --- Step 3: Evaluation C querying narrow window containing only {B, C} ---
    payload_c = {
        "project_id": str(proj.id),
        "start_time": (t + timedelta(seconds=20)).isoformat(),
        "end_time": (t + timedelta(seconds=70)).isoformat(),
    }
    resp_c = client.post("/api/v1/correlations/evaluate", json=payload_c)
    assert resp_c.status_code == 200
    data_c = resp_c.json()
    assert data_c["correlation_groups_count"] == 1
    # Subsumption: must return existing encompassing Group 2, not create a fragmented duplicate group!
    assert data_c["groups"][0]["id"] == group_2_id
    assert data_c["groups"][0]["status"] == "ACTIVE"

    # Verify database still has exactly 2 groups (Group 1 SUPERSEDED, Group 2 ACTIVE)
    all_groups = db_session.query(CorrelationGroup).filter_by(project_id=proj.id).all()
    assert len(all_groups) == 2

    # --- Step 4: Disjoint cascade {D, E} in recommendation & search services ---
    # Register a dependency between recs_svc and search_svc so they form a cluster
    from app.models.service_dependency import ServiceDependency
    dep_rs = ServiceDependency(
        project_id=proj.id,
        source_service_id=recs_svc.id,
        target_service_id=search_svc.id,
        dependency_type="synchronous",
    )
    db_session.add(dep_rs)

    t_disjoint = datetime(2026, 11, 6, 22, 0, 0, tzinfo=timezone.utc)
    ev_d = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=recs_svc.id,
        metric_name="latency",
        observed_value=400.0,
        expected_baseline=40.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t_disjoint,
        status="open",
    )
    ev_e = AnomalyEvent(
        id=uuid4(),
        project_id=proj.id,
        service_id=search_svc.id,
        metric_name="latency",
        observed_value=600.0,
        expected_baseline=60.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t_disjoint + timedelta(seconds=20),
        status="open",
    )
    db_session.add_all([ev_d, ev_e])
    db_session.commit()

    payload_d = {
        "project_id": str(proj.id),
        "start_time": (t_disjoint - timedelta(minutes=1)).isoformat(),
        "end_time": (t_disjoint + timedelta(minutes=2)).isoformat(),
    }
    resp_d = client.post("/api/v1/correlations/evaluate", json=payload_d)
    assert resp_d.status_code == 200
    data_d = resp_d.json()
    assert data_d["correlation_groups_count"] == 1
    group_3_id = data_d["groups"][0]["id"]
    assert group_3_id not in (group_1_id, group_2_id)
    assert data_d["groups"][0]["status"] == "ACTIVE"
    assert data_d["groups"][0]["events_count"] == 2

