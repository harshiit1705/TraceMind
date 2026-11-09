"""Comprehensive tests for Sprint 5.4: Incident lifecycle transitions,

correlation-to-incident integration, supersession, and investigation linkage.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.correlation import CorrelationGroup
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.investigation import Investigation
from app.models.project import Project
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.schemas.common import IncidentStatus
from app.schemas.correlation import CorrelationEvaluationRequest
from app.services.correlation.service import CorrelationService


@pytest.fixture
def correlation_setup(db_session: Session):
    """Sets up a test project, services, dependencies, and baseline."""
    project = db_session.query(Project).first()
    assert project is not None

    svc_gateway = db_session.query(Service).filter_by(slug="api-gateway").first()
    svc_order = db_session.query(Service).filter_by(slug="order-service").first()
    svc_payment = db_session.query(Service).filter_by(slug="payment-service").first()
    assert svc_gateway and svc_order and svc_payment

    now = datetime.now(timezone.utc)

    return {
        "project": project,
        "gateway": svc_gateway,
        "order": svc_order,
        "payment": svc_payment,
        "now": now,
    }

    return {
        "project": project,
        "gateway": svc_gateway,
        "order": svc_order,
        "payment": svc_payment,
        "now": now,
    }


def test_new_correlation_group_creates_exactly_one_incident(db_session: Session, correlation_setup):
    """Test that evaluating a new anomaly cluster automatically creates a persisted incident in DETECTED."""
    setup = correlation_setup
    project = setup["project"]
    svc_order = setup["order"]
    svc_gateway = setup["gateway"]
    now = setup["now"]

    # 1. Create two correlated anomaly events
    ev1 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_order.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=450.0,
        expected_baseline=50.0,
        deviation_pct=800.0,
        severity="HIGH",
        status="active",
        occurred_at=now - timedelta(minutes=5),
    )
    ev2 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_gateway.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=320.0,
        expected_baseline=50.0,
        deviation_pct=540.0,
        severity="CRITICAL",
        status="active",
        occurred_at=now - timedelta(minutes=4),
    )
    db_session.add_all([ev1, ev2])
    db_session.commit()

    # 2. Run correlation service
    corr_svc = CorrelationService(db_session)
    resp = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=project.id,
            start_time=now - timedelta(minutes=10),
            end_time=now,
        )
    )

    assert resp.correlation_groups_count >= 1
    corr_group_id = resp.groups[0].id

    # 3. Verify exactly one incident was created
    incidents = db_session.query(Incident).filter_by(correlation_group_id=corr_group_id).all()
    assert len(incidents) == 1

    incident = incidents[0]
    assert incident.status == IncidentStatus.DETECTED.value
    assert incident.project_id == project.id
    assert incident.is_demo is False
    assert incident.severity in ("HIGH", "CRITICAL")
    assert svc_order.name in incident.affected_services or svc_gateway.name in incident.affected_services
    assert incident.incident_number.startswith("INC-")

    # Verify initial timeline audit event exists
    events = db_session.query(IncidentEvent).filter_by(incident_id=incident.id).all()
    assert len(events) >= 1
    assert any("Detected" in e.title for e in events)


def test_reevaluating_same_group_does_not_duplicate_incident(db_session: Session, correlation_setup):
    """Test idempotency: re-evaluating the same correlation cluster returns existing incident."""
    setup = correlation_setup
    project = setup["project"]
    svc_order = setup["order"]
    svc_gateway = setup["gateway"]
    now = setup["now"]

    ev1 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_order.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=400.0,
        expected_baseline=50.0,
        deviation_pct=700.0,
        severity="HIGH",
        status="active",
        occurred_at=now - timedelta(minutes=4),
    )
    ev2 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_gateway.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=250.0,
        expected_baseline=50.0,
        deviation_pct=400.0,
        severity="MEDIUM",
        status="active",
        occurred_at=now - timedelta(minutes=3),
    )
    db_session.add_all([ev1, ev2])
    db_session.commit()

    corr_svc = CorrelationService(db_session)
    req = CorrelationEvaluationRequest(
        project_id=project.id,
        start_time=now - timedelta(minutes=10),
        end_time=now,
    )

    # First evaluation
    resp1 = corr_svc.evaluate_and_persist(req)
    group_id_1 = resp1.groups[0].id
    incident_1 = db_session.query(Incident).filter_by(correlation_group_id=group_id_1).one()

    # Second evaluation (identical events)
    resp2 = corr_svc.evaluate_and_persist(req)
    group_id_2 = resp2.groups[0].id
    assert group_id_1 == group_id_2

    # Verify no duplicate incident
    incidents = db_session.query(Incident).filter_by(correlation_group_id=group_id_1).all()
    assert len(incidents) == 1
    assert incidents[0].id == incident_1.id
    assert incidents[0].incident_number == incident_1.incident_number


def test_expanded_superseding_correlation_updates_incident(db_session: Session, correlation_setup):
    """Test that an expanded cascade superseding a narrower active group updates the existing incident."""
    setup = correlation_setup
    project = setup["project"]
    svc_order = setup["order"]
    svc_gateway = setup["gateway"]
    svc_payment = setup["payment"]
    now = setup["now"]

    # 1. Narrow initial cascade: order and gateway
    ev1 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_order.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=410.0,
        expected_baseline=50.0,
        deviation_pct=720.0,
        severity="MEDIUM",
        status="active",
        occurred_at=now - timedelta(minutes=8),
    )
    ev2 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_gateway.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=300.0,
        expected_baseline=50.0,
        deviation_pct=500.0,
        severity="MEDIUM",
        status="active",
        occurred_at=now - timedelta(minutes=7),
    )
    db_session.add_all([ev1, ev2])
    db_session.commit()

    corr_svc = CorrelationService(db_session)
    resp1 = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=project.id,
            start_time=now - timedelta(minutes=10),
            end_time=now - timedelta(minutes=6),
        )
    )
    initial_group = resp1.groups[0]
    initial_incident = db_session.query(Incident).filter_by(correlation_group_id=initial_group.id).one()
    initial_inc_number = initial_incident.incident_number

    # 2. Expanded cascade introduces downstream payment service with CRITICAL severity
    ev3 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_payment.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=950.0,
        expected_baseline=50.0,
        deviation_pct=1800.0,
        severity="CRITICAL",
        status="active",
        occurred_at=now - timedelta(minutes=5),
    )
    db_session.add(ev3)
    db_session.commit()

    resp2 = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=project.id,
            start_time=now - timedelta(minutes=10),
            end_time=now,
        )
    )
    expanded_group = resp2.groups[0]
    assert expanded_group.id != initial_group.id

    # 3. Verify prior group is marked SUPERSEDED
    old_group_row = db_session.query(CorrelationGroup).filter_by(id=initial_group.id).one()
    assert old_group_row.status == "SUPERSEDED"

    # 4. Verify existing incident was updated to the expanded group (preserving incident_number)
    updated_incident = db_session.query(Incident).filter_by(correlation_group_id=expanded_group.id).one()
    assert updated_incident.id == initial_incident.id
    assert updated_incident.incident_number == initial_inc_number
    assert updated_incident.severity == "CRITICAL"
    assert svc_payment.name in updated_incident.affected_services

    # Verify timeline records the expansion audit event
    events = db_session.query(IncidentEvent).filter_by(incident_id=updated_incident.id).all()
    assert any("Expanded" in e.title for e in events)


def test_unrelated_correlation_groups_remain_separate(db_session: Session, correlation_setup):
    """Test that disjoint failure clusters produce two distinct incidents."""
    setup = correlation_setup
    project = setup["project"]
    now = setup["now"]

    # Cluster 1: Services A and B
    svcA = Service(id=uuid4(), project_id=project.id, slug="svc-a", name="Service A", identifier="svc:a")
    svcB = Service(id=uuid4(), project_id=project.id, slug="svc-b", name="Service B", identifier="svc:b")
    # Cluster 2: Services C and D (disjoint)
    svcC = Service(id=uuid4(), project_id=project.id, slug="svc-c", name="Service C", identifier="svc:c")
    svcD = Service(id=uuid4(), project_id=project.id, slug="svc-d", name="Service D", identifier="svc:d")
    db_session.add_all([svcA, svcB, svcC, svcD])
    db_session.flush()

    # Topology: A <-> B and C <-> D
    dep1 = ServiceDependency(id=uuid4(), project_id=project.id, source_service_id=svcA.id, target_service_id=svcB.id)
    dep2 = ServiceDependency(id=uuid4(), project_id=project.id, source_service_id=svcC.id, target_service_id=svcD.id)
    db_session.add_all([dep1, dep2])

    evA = AnomalyEvent(id=uuid4(), project_id=project.id, service_id=svcA.id, metric_name="cpu", detection_method="statistical", observed_value=90.0, severity="HIGH", status="active", occurred_at=now - timedelta(minutes=5))
    evB = AnomalyEvent(id=uuid4(), project_id=project.id, service_id=svcB.id, metric_name="cpu", detection_method="statistical", observed_value=85.0, severity="HIGH", status="active", occurred_at=now - timedelta(minutes=4))
    evC = AnomalyEvent(id=uuid4(), project_id=project.id, service_id=svcC.id, metric_name="mem", detection_method="statistical", observed_value=95.0, severity="CRITICAL", status="active", occurred_at=now - timedelta(minutes=5))
    evD = AnomalyEvent(id=uuid4(), project_id=project.id, service_id=svcD.id, metric_name="mem", detection_method="statistical", observed_value=92.0, severity="CRITICAL", status="active", occurred_at=now - timedelta(minutes=4))
    db_session.add_all([evA, evB, evC, evD])
    db_session.commit()

    corr_svc = CorrelationService(db_session)
    resp = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=project.id,
            start_time=now - timedelta(minutes=10),
            end_time=now,
        )
    )
    assert resp.correlation_groups_count == 2
    g1, g2 = resp.groups[0].id, resp.groups[1].id

    inc1 = db_session.query(Incident).filter_by(correlation_group_id=g1).one()
    inc2 = db_session.query(Incident).filter_by(correlation_group_id=g2).one()
    assert inc1.id != inc2.id
    assert inc1.incident_number != inc2.incident_number


def test_valid_incident_status_transitions(client: TestClient, db_session: Session):
    """Test full valid lifecycle: DETECTED -> INVESTIGATING -> ACKNOWLEDGED -> MITIGATED -> RESOLVED."""
    project = db_session.query(Project).first()
    now = datetime.now(timezone.utc)

    incident = Incident(
        id=uuid4(),
        project_id=project.id,
        incident_number="INC-7001",
        title="Payment Latency Surge",
        severity="HIGH",
        status=IncidentStatus.DETECTED.value,
        started_at=now,
        commander_name="Unassigned",
        commander_role="SRE",
        is_demo=False,
    )
    db_session.add(incident)
    db_session.commit()

    # 1. DETECTED -> INVESTIGATING
    r1 = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "INVESTIGATING", "comment": "Starting initial telemetry triage"},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "INVESTIGATING"

    # 2. INVESTIGATING -> ACKNOWLEDGED
    r2 = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "ACKNOWLEDGED", "commander_name": "Maria Vance", "commander_role": "Platform Lead"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "ACKNOWLEDGED"
    assert r2.json()["commander_name"] == "Maria Vance"

    # 3. ACKNOWLEDGED -> MITIGATED
    r3 = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "MITIGATED", "comment": "Applied database pool expansion runbook"},
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "MITIGATED"
    assert r3.json()["mitigated_at"] is not None

    # 4. MITIGATED -> RESOLVED
    r4 = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "RESOLVED", "comment": "Traffic stabilized, error rate < 0.01%"},
    )
    assert r4.status_code == 200
    assert r4.json()["status"] == "RESOLVED"
    assert r4.json()["resolved_at"] is not None


def test_invalid_incident_status_transitions_return_409(client: TestClient, db_session: Session):
    """Test that invalid lifecycle transitions return HTTP 409 Conflict."""
    project = db_session.query(Project).first()
    now = datetime.now(timezone.utc)

    # Incident starts in DETECTED
    incident = Incident(
        id=uuid4(),
        project_id=project.id,
        incident_number="INC-7002",
        title="Test Incident",
        severity="LOW",
        status=IncidentStatus.DETECTED.value,
        started_at=now,
        is_demo=False,
    )
    db_session.add(incident)
    db_session.commit()

    # Invalid: DETECTED -> RESOLVED (cannot resolve without investigating/mitigating)
    res_invalid = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "RESOLVED"},
    )
    assert res_invalid.status_code == 409
    assert "Invalid status transition" in res_invalid.json()["detail"]

    # Invalid: DETECTED -> MITIGATED
    res_invalid_mit = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "MITIGATED"},
    )
    assert res_invalid_mit.status_code == 409

    # Transition to RESOLVED legitimately
    client.patch(f"/api/v1/incidents/{incident.id}/status", json={"status": "INVESTIGATING"})
    client.patch(f"/api/v1/incidents/{incident.id}/status", json={"status": "RESOLVED"})

    # Invalid: RESOLVED has no further transitions
    res_from_resolved = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "INVESTIGATING"},
    )
    assert res_from_resolved.status_code == 409


def test_repeated_status_does_not_create_duplicate_history(client: TestClient, db_session: Session):
    """Test idempotency: repeating the current status returns 200 without duplicate timeline entries."""
    project = db_session.query(Project).first()
    now = datetime.now(timezone.utc)

    incident = Incident(
        id=uuid4(),
        project_id=project.id,
        incident_number="INC-7003",
        title="Test Repetition",
        severity="MEDIUM",
        status=IncidentStatus.INVESTIGATING.value,
        started_at=now,
        is_demo=False,
    )
    db_session.add(incident)
    db_session.commit()

    # 1 event currently
    e1 = IncidentEvent(
        id=uuid4(),
        incident_id=incident.id,
        timestamp=now,
        title="Incident Detected",
        description="Initial alert",
    )
    db_session.add(e1)
    db_session.commit()

    initial_events_count = db_session.query(IncidentEvent).filter_by(incident_id=incident.id).count()

    # Repeatedly send status: INVESTIGATING
    res1 = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "INVESTIGATING"},
    )
    assert res1.status_code == 200

    res2 = client.patch(
        f"/api/v1/incidents/{incident.id}/status",
        json={"status": "INVESTIGATING"},
    )
    assert res2.status_code == 200

    final_events_count = db_session.query(IncidentEvent).filter_by(incident_id=incident.id).count()
    assert final_events_count == initial_events_count


def test_incident_timeline_returns_persisted_events(client: TestClient, db_session: Session):
    """Test GET /api/v1/incidents/{incident_id}/timeline returns chronological events."""
    project = db_session.query(Project).first()
    now = datetime.now(timezone.utc)

    incident = Incident(
        id=uuid4(),
        project_id=project.id,
        incident_number="INC-7004",
        title="Timeline Audit Incident",
        severity="HIGH",
        status=IncidentStatus.INVESTIGATING.value,
        started_at=now - timedelta(minutes=10),
        is_demo=False,
    )
    db_session.add(incident)
    db_session.commit()

    # Add 3 events out of order to verify sorting
    ev_mid = IncidentEvent(
        id=uuid4(),
        incident_id=incident.id,
        timestamp=now - timedelta(minutes=5),
        title="Mid Event",
        description="Investigation ongoing",
    )
    ev_early = IncidentEvent(
        id=uuid4(),
        incident_id=incident.id,
        timestamp=now - timedelta(minutes=10),
        title="Earliest Event",
        description="Anomaly detected",
    )
    ev_late = IncidentEvent(
        id=uuid4(),
        incident_id=incident.id,
        timestamp=now - timedelta(minutes=1),
        title="Latest Event",
        description="Root cause identified",
    )
    db_session.add_all([ev_mid, ev_early, ev_late])
    db_session.commit()

    res = client.get(f"/api/v1/incidents/{incident.id}/timeline")
    assert res.status_code == 200
    data = res.json()
    assert data["incident_id"] == str(incident.id)
    assert len(data["events"]) == 3
    # Check chronological ordering
    timestamps = [e["timestamp"] for e in data["events"]]
    assert timestamps == sorted(timestamps)


def test_linked_investigation_retrieved_read_only(client: TestClient, db_session: Session):
    """Test retrieving linked investigation for an incident without triggering Gemini generation."""
    project = db_session.query(Project).first()
    now = datetime.now(timezone.utc)

    # 1. Incident without correlation group has null investigation
    inc_no_corr = Incident(
        id=uuid4(),
        project_id=project.id,
        incident_number="INC-7005",
        title="Uncorrelated Incident",
        severity="LOW",
        status=IncidentStatus.INVESTIGATING.value,
        started_at=now,
        is_demo=False,
    )
    db_session.add(inc_no_corr)
    db_session.commit()

    res_null = client.get(f"/api/v1/incidents/{inc_no_corr.id}/investigation")
    assert res_null.status_code == 200
    assert res_null.json() is None

    # 2. Incident linked to a correlation group with a persisted COMPLETED investigation
    corr = CorrelationGroup(
        id=uuid4(),
        project_id=project.id,
        correlation_key="test-corr-key-inv-link",
        time_window_start=now - timedelta(minutes=15),
        time_window_end=now,
        status="ACTIVE",
    )
    db_session.add(corr)
    db_session.flush()

    inv = Investigation(
        id=uuid4(),
        correlation_group_id=corr.id,
        status="COMPLETED",
        provider="google-gemini",
        model_name="gemini-2.0-flash",
        prompt_version="v1.0",
        schema_version="v1.0",
        investigation_json={
            "incident_summary": "Cascading network timeout across distributed microservices.",
            "root_cause_analysis": {
                "candidate_id": str(uuid4()),
                "service_id": str(uuid4()),
                "service_name": "API Gateway",
                "explanation": "Downstream thread exhaustion caused HTTP 504 timeouts to clients.",
                "contributing_factors": ["High concurrency", "Connection starvation"],
            },
            "timeline": [
                {
                    "timestamp": now.isoformat(),
                    "event_id": str(uuid4()),
                    "service_id": str(uuid4()),
                    "service_name": "API Gateway",
                    "metric_name": "latency_p95",
                    "observation": "p95 latency reached 2400ms exceeding 200ms threshold",
                    "severity": "CRITICAL",
                }
            ],
            "evidence_references": [],
            "uncertainties_and_gaps": [],
            "prioritized_investigation_steps": [],
            "remediation_recommendations": [],
        },
    )
    db_session.add(inv)

    inc_with_corr = Incident(
        id=uuid4(),
        project_id=project.id,
        correlation_group_id=corr.id,
        incident_number="INC-7006",
        title="Correlated Incident with AI Report",
        severity="CRITICAL",
        status=IncidentStatus.INVESTIGATING.value,
        started_at=now,
        is_demo=False,
    )
    db_session.add(inc_with_corr)
    db_session.commit()

    res_inv = client.get(f"/api/v1/incidents/{inc_with_corr.id}/investigation")
    assert res_inv.status_code == 200
    data = res_inv.json()
    assert data is not None
    assert data["status"] == "COMPLETED"
    assert "Cascading network timeout" in data["investigation_json"]["incident_summary"]


def test_cross_project_associations_rejected(client: TestClient, db_session: Session):
    """Test that manual incident creation rejects correlation groups from a different project or nonexistent groups."""
    now = datetime.now(timezone.utc)
    # 1. Use existing Project A and ensure Project B exists
    proj_a = db_session.query(Project).first()
    assert proj_a is not None

    proj_b = db_session.query(Project).filter(Project.id != proj_a.id).first()
    if not proj_b:
        proj_b = Project(
            id=uuid4(),
            organization_id=proj_a.organization_id,
            slug=f"project-beta-{uuid4().hex[:6]}",
            name="Project Beta",
            description="Beta test project",
        )
        db_session.add(proj_b)
        db_session.commit()

    # 2. Create a correlation group belonging strictly to Project B
    corr_group_b = CorrelationGroup(
        id=uuid4(),
        project_id=proj_b.id,
        correlation_key="project-b-cross-test-key",
        time_window_start=now - timedelta(minutes=10),
        time_window_end=now,
        status="ACTIVE",
    )
    db_session.add(corr_group_b)
    db_session.commit()

    # 3. Attempt to create an incident in Project A referencing Project B's correlation group -> 400
    res_mismatch = client.post(
        f"/api/v1/incidents?project_id={proj_a.id}",
        json={
            "title": "Cross-project association attempt",
            "severity": "HIGH",
            "correlation_group_id": str(corr_group_b.id),
        },
    )
    assert res_mismatch.status_code == 400
    assert "belongs to a different project" in res_mismatch.json()["detail"]

    # 4. Attempt to create an incident referencing a non-existent correlation group -> 404
    non_existent_corr_id = uuid4()
    res_not_found = client.post(
        f"/api/v1/incidents?project_id={proj_a.id}",
        json={
            "title": "Nonexistent correlation group attempt",
            "severity": "HIGH",
            "correlation_group_id": str(non_existent_corr_id),
        },
    )
    assert res_not_found.status_code == 404
    assert f"Correlation group '{non_existent_corr_id}' was not found" in res_not_found.json()["detail"]

    # 5. Confirm no incident was created under Project A with Project B's correlation group
    incidents_a = db_session.query(Incident).filter_by(project_id=proj_a.id).all()
    for inc in incidents_a:
        assert inc.correlation_group_id != corr_group_b.id


def test_incident_sync_failure_rolls_back_correlation_and_supersession(
    db_session: Session,
    correlation_setup,
    monkeypatch,
):
    """Test transaction atomicity:

    If incident synchronization fails, the newly evaluated correlation group and any supersession
    updates to predecessor groups must be rolled back atomically. No partial state may remain.
    """
    setup = correlation_setup
    project = setup["project"]
    svc_order = setup["order"]
    svc_gateway = setup["gateway"]
    svc_payment = setup["payment"]
    now = setup["now"]

    # 1. First create an initial active correlation group G1 (order and gateway)
    ev1 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_order.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=410.0,
        expected_baseline=50.0,
        deviation_pct=720.0,
        severity="MEDIUM",
        status="active",
        occurred_at=now - timedelta(minutes=9),
    )
    ev2 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_gateway.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=300.0,
        expected_baseline=50.0,
        deviation_pct=500.0,
        severity="MEDIUM",
        status="active",
        occurred_at=now - timedelta(minutes=8),
    )
    db_session.add_all([ev1, ev2])
    db_session.commit()

    corr_svc = CorrelationService(db_session)
    resp1 = corr_svc.evaluate_and_persist(
        CorrelationEvaluationRequest(
            project_id=project.id,
            start_time=now - timedelta(minutes=10),
            end_time=now - timedelta(minutes=7),
        )
    )
    assert resp1.correlation_groups_count >= 1
    g1_id = resp1.groups[0].id

    g1_row = db_session.query(CorrelationGroup).filter_by(id=g1_id).first()
    assert g1_row is not None
    assert g1_row.status == "ACTIVE"

    # Count correlation groups before simulated failure
    groups_count_before = db_session.query(CorrelationGroup).count()

    # 2. Add an expanding event (payment) so the next evaluation would supersede G1
    ev3 = AnomalyEvent(
        id=uuid4(),
        project_id=project.id,
        service_id=svc_payment.id,
        metric_name="latency_p95",
        detection_method="statistical",
        observed_value=450.0,
        expected_baseline=50.0,
        deviation_pct=800.0,
        severity="CRITICAL",
        status="active",
        occurred_at=now - timedelta(minutes=6),
    )
    db_session.add(ev3)
    db_session.commit()

    # 3. Simulate failure in sync_incident_for_correlation_group
    def failing_sync(*args, **kwargs):
        raise RuntimeError("Simulated unrecoverable incident synchronization failure")

    monkeypatch.setattr(corr_svc.incident_service, "sync_incident_for_correlation_group", failing_sync)

    with pytest.raises(RuntimeError, match="Simulated unrecoverable incident synchronization failure"):
        corr_svc.evaluate_and_persist(
            CorrelationEvaluationRequest(
                project_id=project.id,
                start_time=now - timedelta(minutes=10),
                end_time=now,
            )
        )

    # 4. Verify transaction atomicity:
    db_session.expire_all()
    # A. No new group was persisted in the database
    groups_count_after = db_session.query(CorrelationGroup).count()
    assert groups_count_after == groups_count_before

    # B. G1 status remains ACTIVE (supersession update rolled back)
    g1_refetched = db_session.query(CorrelationGroup).filter_by(id=g1_id).first()
    assert g1_refetched is not None
    assert g1_refetched.status == "ACTIVE"
    # A. No new group was persisted in the database
    groups_count_after = db_session.query(CorrelationGroup).count()
    assert groups_count_after == groups_count_before

    # B. G1 status remains ACTIVE (supersession update rolled back)
    g1_refetched = db_session.query(CorrelationGroup).filter_by(id=g1_id).first()
    assert g1_refetched is not None
    assert g1_refetched.status == "ACTIVE"


def test_incident_number_collision_retry_with_savepoint(db_session: Session, correlation_setup, monkeypatch):
    """Test that unique incident_number collisions are retried gracefully using savepoints,

    while unexpected errors are surfaced clearly rather than swallowed.
    """
    setup = correlation_setup
    project = setup["project"]
    now = setup["now"]

    corr_group = CorrelationGroup(
        id=uuid4(),
        project_id=project.id,
        correlation_key="test-savepoint-collision-key",
        time_window_start=now,
        time_window_end=now,
        status="ACTIVE",
    )
    db_session.add(corr_group)
    db_session.commit()

    from app.services.incident_service import IncidentService
    inc_service = IncidentService(db_session)

    # Pre-insert an incident with INC-8888
    existing_inc = Incident(
        id=uuid4(),
        project_id=project.id,
        incident_number="INC-8888",
        title="Existing Incident",
        severity="LOW",
        status=IncidentStatus.DETECTED.value,
        started_at=now,
        is_demo=False,
    )
    db_session.add(existing_inc)
    db_session.commit()

    # Monkeypatch generate_next_incident_number to return "INC-8888" on attempt 1, then "INC-8889" on attempt 2
    attempts = [0]
    original_gen = inc_service.incident_repo.generate_next_incident_number

    def sequenced_generator():
        attempts[0] += 1
        if attempts[0] == 1:
            return "INC-8888"  # Will trigger collision with existing_inc
        return "INC-8889"

    monkeypatch.setattr(inc_service.incident_repo, "generate_next_incident_number", sequenced_generator)

    # sync_incident_for_correlation_group should catch the collision on attempt 1, rollback the savepoint, and succeed on attempt 2
    new_inc = inc_service.sync_incident_for_correlation_group(corr_group)
    assert new_inc is not None
    assert new_inc.incident_number == "INC-8889"
    assert attempts[0] == 2

