"""Comprehensive tests for Phase 2: Multi-Signal Evidence Retrieval & Deterministic Root Cause Analysis.

Covers Scenarios A-F:
- Scenario A: Payment Service Latency Cascade (outer caller span wrapper MUST NOT beat leaf bottleneck)
- Scenario B: Inventory Service Latency Cascade (unrelated Payment Service remains neutral)
- Scenario C: Payment Service 502 Errors (origin error leaf span + error log deduplication)
- Scenario D: Recovery After Remediation (healthy recovery telemetry creates zero new incidents & RESOLVED snapshot immutable)
- Scenario E: Ambiguous / Incomplete Evidence (missing signals stay neutral without fake certainty)
- Scenario F: Contradictory Evidence (trace/log signals contradict standalone anomaly claim; confidence lowered & surfaced)
Plus API contracts for GET /correlations/{id}/evidence, POST /correlations/{id}/recalculate, and GET /incidents/{id}/evidence.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.correlation import CorrelationGroup
from app.models.incident import Incident
from app.models.organization import Organization
from app.models.project import Project
from app.models.service import Service
from app.models.telemetry import ApplicationLog, MetricSample, TraceSpan
from app.schemas.correlation import RankingConfidence


def _get_core_services(db: Session):
    proj = db.query(Project).filter_by(slug="core-ecommerce").first()
    assert proj is not None
    order_svc = db.query(Service).filter_by(project_id=proj.id, slug="order-service").first()
    pay_svc = db.query(Service).filter_by(project_id=proj.id, slug="payment-service").first()
    inv_svc = db.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    assert order_svc and pay_svc and inv_svc
    return proj, order_svc, pay_svc, inv_svc


def _add_anomaly(
    db: Session,
    project_id: UUID,
    service_id: UUID,
    metric_name: str,
    observed: float,
    baseline: float,
    dev_pct: float,
    occurred_at: datetime,
    severity: str = "critical",
) -> AnomalyEvent:
    ev = AnomalyEvent(
        id=uuid4(),
        project_id=project_id,
        service_id=service_id,
        metric_name=metric_name,
        observed_value=observed,
        expected_baseline=baseline,
        deviation_pct=dev_pct,
        severity=severity,
        detection_method="rolling_average",
        occurred_at=occurred_at,
        status="open",
        explanation=f"{metric_name} anomaly observed",
    )
    db.add(ev)
    return ev


def _add_metric(
    db: Session,
    project_id: UUID,
    service_id: UUID,
    metric_name: str,
    value: float,
    ts: datetime,
    unit: str = "ms",
    trace_id: str | None = None,
) -> MetricSample:
    row = MetricSample(
        id=uuid4(),
        project_id=project_id,
        service_id=service_id,
        metric_name=metric_name,
        metric_unit=unit,
        value=value,
        timestamp=ts,
        endpoint="POST /charge",
        trace_id=trace_id,
        attributes_json={},
    )
    db.add(row)
    return row


def _add_log(
    db: Session,
    project_id: UUID,
    service_id: UUID,
    ts: datetime,
    level: str,
    message: str,
    trace_id: str | None = None,
    exception_type: str | None = None,
) -> ApplicationLog:
    row = ApplicationLog(
        id=uuid4(),
        project_id=project_id,
        service_id=service_id,
        timestamp=ts,
        level=level,
        message=message,
        trace_id=trace_id,
        attributes_json={},
        exception_type=exception_type,
    )
    db.add(row)
    return row


def _add_span(
    db: Session,
    project_id: UUID,
    service_id: UUID,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    op: str,
    kind: str,
    start_ts: datetime,
    duration_ms: float,
    status: str = "ok",
    http_status: int = 200,
    error_message: str | None = None,
) -> TraceSpan:
    row = TraceSpan(
        id=uuid4(),
        project_id=project_id,
        service_id=service_id,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        operation_name=op,
        span_kind=kind,
        start_time=start_ts,
        end_time=start_ts + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        status=status,
        http_status_code=http_status,
        error_message=error_message,
        attributes_json={},
    )
    db.add(row)
    return row


def test_scenario_a_payment_latency_excludes_outer_wrapper_and_ranks_payment_first(
    client: TestClient,
    db_session: Session,
):
    """Scenario A: Payment latency cascade where Order server span (830ms) wraps Payment leaf span (800ms).
    Exclusive self-time MUST credit payment-service (~96% self-time) and NOT blame order-service (~30ms self-time).
    """
    proj, order_svc, pay_svc, _ = _get_core_services(db_session)
    t0 = datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc)

    # Baseline metrics (T - 5 min)
    for i in range(4):
        bt = t0 - timedelta(minutes=5) + timedelta(seconds=i * 10)
        _add_metric(db_session, proj.id, pay_svc.id, "latency", 45.0, bt)
        _add_metric(db_session, proj.id, order_svc.id, "latency", 75.0, bt)

    # Incident window metrics + anomalies + warnings + traces
    for i in range(5):
        it = t0 + timedelta(seconds=i * 5)
        tid = f"trace-pay-lat-{i}"
        _add_metric(db_session, proj.id, pay_svc.id, "latency", 805.0 + i, it, trace_id=tid)
        _add_metric(db_session, proj.id, order_svc.id, "latency", 840.0 + i, it, trace_id=tid)

        # Parent-child waterfall: order server (835ms) -> order client (815ms) -> payment server (810ms) -> payment.gateway_charge (800ms)
        _add_span(db_session, proj.id, order_svc.id, tid, f"sp-ord-srv-{i}", None, "POST /orders", "server", it, 835.0)
        _add_span(db_session, proj.id, order_svc.id, tid, f"sp-ord-cli-{i}", f"sp-ord-srv-{i}", "HTTP POST payment-service/charge", "client", it + timedelta(milliseconds=10), 815.0)
        _add_span(db_session, proj.id, pay_svc.id, tid, f"sp-pay-srv-{i}", f"sp-ord-cli-{i}", "POST /charge", "server", it + timedelta(milliseconds=12), 810.0)
        _add_span(db_session, proj.id, pay_svc.id, tid, f"sp-pay-gw-{i}", f"sp-pay-srv-{i}", "payment.gateway_charge", "internal", it + timedelta(milliseconds=15), 800.0)

        _add_log(db_session, proj.id, pay_svc.id, it, "WARNING", f"Slow request detected on POST /charge: {805+i}ms", trace_id=tid)
        _add_log(db_session, proj.id, order_svc.id, it + timedelta(milliseconds=830), "WARNING", f"Slow request detected on POST /orders: {835+i}ms", trace_id=tid)

    _add_anomaly(db_session, proj.id, pay_svc.id, "latency", 808.0, 45.0, 1695.0, t0, "critical")
    _add_anomaly(db_session, proj.id, order_svc.id, "latency", 842.0, 75.0, 1022.0, t0 + timedelta(seconds=10), "high")
    db_session.commit()

    resp = client.post(
        "/api/v1/correlations/evaluate",
        json={
            "project_id": str(proj.id),
            "start_time": (t0 - timedelta(minutes=1)).isoformat(),
            "end_time": (t0 + timedelta(minutes=1)).isoformat(),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlation_groups_count"] == 1
    group = data["groups"][0]

    top = group["ranked_candidates"][0]
    second = group["ranked_candidates"][1]
    assert top["service_slug"] == "payment-service"
    assert top["rank"] == 1
    assert top["scoring_mode"] == "multi_signal_v2"
    assert top["confidence"] == "HIGH"
    assert top["primary_suspected_operation"] == "payment.gateway_charge"
    assert "Order Service" in top["affected_downstream_services"]

    # Trace bottleneck score MUST strongly favor payment-service over order-service
    assert top["breakdown"]["trace_bottleneck"]["available"] is True
    assert top["breakdown"]["trace_bottleneck"]["score"] >= 0.85
    assert second["service_slug"] == "order-service"
    assert second["breakdown"]["trace_bottleneck"]["score"] <= 0.15

    # Active weights sum to 1.0
    b = top["breakdown"]
    weight_sum = (
        b["temporal_precedence"]["weight"]
        + b["topological_position"]["weight"]
        + b["blast_radius"]["weight"]
        + b["severity_magnitude"]["weight"]
        + b["metric_deviation"]["weight"]
        + b["log_evidence"]["weight"]
        + b["trace_bottleneck"]["weight"]
    )
    assert abs(weight_sum - 1.0) < 0.005

    # Check GET /correlations/{id}/evidence & GET /incidents/{id}/evidence
    ev_resp = client.get(f"/api/v1/correlations/{group['id']}/evidence")
    assert ev_resp.status_code == 200
    ev_data = ev_resp.json()
    assert ev_data["coverage"]["metrics_available"] is True
    assert ev_data["coverage"]["logs_available"] is True
    assert ev_data["coverage"]["traces_available"] is True
    assert ev_data["primary_suspected_operation"].endswith("payment.gateway_charge")

    inc = db_session.query(Incident).filter_by(correlation_group_id=UUID(group["id"])).first()
    assert inc is not None
    inc_ev_resp = client.get(f"/api/v1/incidents/{inc.incident_number}/evidence")
    assert inc_ev_resp.status_code == 200
    inc_ev = inc_ev_resp.json()
    assert inc_ev["is_demo_scenario"] is False
    ev_types = {item["evidence_type"] for item in inc_ev["items"]}
    assert {"metric", "log", "trace", "topology"}.issubset(ev_types)


def test_scenario_b_inventory_latency_keeps_healthy_payment_neutral(
    client: TestClient,
    db_session: Session,
):
    """Scenario B: Inventory Service injects latency; Order degrades calling Inventory; Payment remains healthy."""
    proj, order_svc, pay_svc, inv_svc = _get_core_services(db_session)
    t0 = datetime(2026, 11, 10, 11, 0, 0, tzinfo=timezone.utc)

    for i in range(5):
        it = t0 + timedelta(seconds=i * 4)
        tid = f"trace-inv-lat-{i}"
        _add_metric(db_session, proj.id, inv_svc.id, "latency", 660.0, it, trace_id=tid)
        _add_metric(db_session, proj.id, order_svc.id, "latency", 710.0, it, trace_id=tid)
        # Healthy payment samples
        _add_metric(db_session, proj.id, pay_svc.id, "latency", 35.0, it, trace_id=tid)

        _add_span(db_session, proj.id, order_svc.id, tid, f"ord-s-{i}", None, "POST /orders", "server", it, 715.0)
        _add_span(db_session, proj.id, inv_svc.id, tid, f"inv-s-{i}", f"ord-s-{i}", "POST /reserve", "server", it + timedelta(milliseconds=5), 670.0)
        _add_span(db_session, proj.id, pay_svc.id, tid, f"pay-s-{i}", f"ord-s-{i}", "POST /charge", "server", it + timedelta(milliseconds=680), 32.0)

    _add_anomaly(db_session, proj.id, inv_svc.id, "latency", 660.0, 35.0, 1785.0, t0, "critical")
    _add_anomaly(db_session, proj.id, order_svc.id, "latency", 710.0, 80.0, 787.0, t0 + timedelta(seconds=8), "high")
    db_session.commit()

    resp = client.post(
        "/api/v1/correlations/evaluate",
        json={
            "project_id": str(proj.id),
            "start_time": (t0 - timedelta(minutes=1)).isoformat(),
            "end_time": (t0 + timedelta(minutes=1)).isoformat(),
        },
    )
    assert resp.status_code == 200
    group = resp.json()["groups"][0]
    top = group["ranked_candidates"][0]
    assert top["service_slug"] == "inventory-service"
    assert top["confidence"] == "HIGH"
    assert top["primary_suspected_operation"] == "POST /reserve"
    # Payment service had no anomaly & wasn't falsely accused
    candidate_slugs = {c["service_slug"] for c in group["ranked_candidates"]}
    assert "payment-service" not in candidate_slugs


def test_scenario_c_payment_errors_origin_span_and_log_deduplication(
    client: TestClient,
    db_session: Session,
):
    """Scenario C: Payment 502 error spike; duplicate logs on the same trace are deduplicated cleanly."""
    proj, order_svc, pay_svc, _ = _get_core_services(db_session)
    t0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)

    for i in range(4):
        it = t0 + timedelta(seconds=i * 3)
        tid = f"trace-pay-err-{i}"
        _add_metric(db_session, proj.id, pay_svc.id, "error_rate", 100.0, it, unit="%", trace_id=tid)
        _add_metric(db_session, proj.id, order_svc.id, "error_rate", 100.0, it, unit="%", trace_id=tid)

        _add_span(db_session, proj.id, order_svc.id, tid, f"ord-srv-{i}", None, "POST /orders", "server", it, 65.0, status="error", http_status=502, error_message="Downstream bad gateway")
        _add_span(db_session, proj.id, pay_svc.id, tid, f"pay-srv-{i}", f"ord-srv-{i}", "POST /charge", "server", it + timedelta(milliseconds=8), 45.0, status="error", http_status=502, error_message="Injected payment gateway 502 error")

        _add_log(db_session, proj.id, pay_svc.id, it, "ERROR", "Injected payment gateway 502 error [password=secret123]", trace_id=tid, exception_type="GatewayError")
        _add_log(db_session, proj.id, order_svc.id, it + timedelta(milliseconds=60), "ERROR", "Downstream payment-service failed with status 502", trace_id=tid)

    # Extra repeated error log lines for the SAME trace on order-service should NOT inflate Order above Payment!
    for j in range(5):
        _add_log(db_session, proj.id, order_svc.id, t0 + timedelta(milliseconds=100 + j), "ERROR", f"Retry attempt {j+1} failed calling downstream payment-service 502", trace_id="trace-pay-err-0")

    _add_anomaly(db_session, proj.id, pay_svc.id, "error_rate", 100.0, 0.0, 1000.0, t0, "critical")
    _add_anomaly(db_session, proj.id, order_svc.id, "error_rate", 100.0, 0.0, 1000.0, t0 + timedelta(seconds=2), "high")
    db_session.commit()

    resp = client.post(
        "/api/v1/correlations/evaluate",
        json={
            "project_id": str(proj.id),
            "start_time": (t0 - timedelta(minutes=1)).isoformat(),
            "end_time": (t0 + timedelta(minutes=1)).isoformat(),
        },
    )
    assert resp.status_code == 200
    group = resp.json()["groups"][0]
    top = group["ranked_candidates"][0]
    assert top["service_slug"] == "payment-service"
    assert top["confidence"] == "HIGH"
    assert top["breakdown"]["trace_bottleneck"]["score"] >= 0.85
    # Verify redaction happened on logs in evidence_summary
    msgs = " ".join(lg["message"] for lg in group["evidence_summary"]["log_highlights"])
    assert "secret123" not in msgs


def test_scenario_d_recovery_creates_no_new_incidents_and_resolved_is_immutable(
    client: TestClient,
    db_session: Session,
):
    """Scenario D: Healthy post-recovery traffic produces zero new groups; RESOLVED correlation snapshot is immutable."""
    proj, order_svc, pay_svc, _ = _get_core_services(db_session)
    t_inc = datetime(2026, 11, 10, 13, 0, 0, tzinfo=timezone.utc)
    _add_anomaly(db_session, proj.id, pay_svc.id, "latency", 800.0, 50.0, 1500.0, t_inc, "critical")
    _add_anomaly(db_session, proj.id, order_svc.id, "latency", 830.0, 80.0, 937.5, t_inc + timedelta(seconds=5), "high")
    db_session.commit()

    eval_resp = client.post(
        "/api/v1/correlations/evaluate",
        json={
            "project_id": str(proj.id),
            "start_time": (t_inc - timedelta(minutes=1)).isoformat(),
            "end_time": (t_inc + timedelta(minutes=1)).isoformat(),
        },
    )
    assert eval_resp.status_code == 200
    gid = eval_resp.json()["groups"][0]["id"]

    # Mark correlation group and incident RESOLVED
    grp_row = db_session.query(CorrelationGroup).filter_by(id=UUID(gid)).first()
    grp_row.status = "RESOLVED"
    db_session.commit()

    # Post-recovery window has ONLY healthy metrics, INFO logs, fast 200 OK spans, ZERO anomalies
    t_rec = t_inc + timedelta(minutes=15)
    for i in range(4):
        rt = t_rec + timedelta(seconds=i * 5)
        _add_metric(db_session, proj.id, pay_svc.id, "latency", 42.0, rt, trace_id=f"rec-{i}")
        _add_log(db_session, proj.id, pay_svc.id, rt, "INFO", "POST /charge completed 200 OK", trace_id=f"rec-{i}")
        _add_span(db_session, proj.id, pay_svc.id, f"rec-{i}", f"rec-sp-{i}", None, "POST /charge", "server", rt, 40.0)
    db_session.commit()

    rec_eval = client.post(
        "/api/v1/correlations/evaluate",
        json={
            "project_id": str(proj.id),
            "start_time": (t_rec - timedelta(minutes=1)).isoformat(),
            "end_time": (t_rec + timedelta(minutes=1)).isoformat(),
        },
    )
    assert rec_eval.status_code == 200
    assert rec_eval.json()["correlation_groups_count"] == 0

    # Recalculating a RESOLVED correlation group MUST return 409 Conflict (immutability preserved)
    recalc_resp = client.post(f"/api/v1/correlations/{gid}/recalculate")
    assert recalc_resp.status_code == 409


def test_scenario_e_ambiguous_incomplete_evidence_bounds_confidence_neutrally(
    client: TestClient,
    db_session: Session,
):
    """Scenario E: Unmapped topology + missing logs/traces + tied anomalies -> bounded confidence, explicit missing signals."""
    org = db_session.query(Organization).first()
    proj = Project(organization_id=org.id, slug="ambig-proj", name="Ambiguous Proj", environment="test")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    s1 = Service(project_id=proj.id, slug="alpha-svc", name="Alpha Service", identifier="svc:alpha")
    s2 = Service(project_id=proj.id, slug="beta-svc", name="Beta Service", identifier="svc:beta")
    db_session.add_all([s1, s2])
    db_session.commit()

    t0 = datetime(2026, 11, 10, 14, 0, 0, tzinfo=timezone.utc)
    # Simultaneous identical anomalies, only sparse metrics, NO logs, NO traces, NO topology edges
    _add_metric(db_session, proj.id, s1.id, "latency", 400.0, t0)
    _add_metric(db_session, proj.id, s2.id, "latency", 400.0, t0)
    _add_anomaly(db_session, proj.id, s1.id, "latency", 400.0, 100.0, 300.0, t0, "high")
    _add_anomaly(db_session, proj.id, s2.id, "latency", 400.0, 100.0, 300.0, t0, "high")
    db_session.commit()

    resp = client.post(
        "/api/v1/correlations/evaluate",
        json={
            "project_id": str(proj.id),
            "start_time": (t0 - timedelta(minutes=1)).isoformat(),
            "end_time": (t0 + timedelta(minutes=1)).isoformat(),
        },
    )
    assert resp.status_code == 200
    group = resp.json()["groups"][0]
    top = group["ranked_candidates"][0]
    assert top["confidence"] in ("LOW", "MEDIUM")
    assert top["confidence"] != "HIGH"
    assert "logs" in top["missing_signals"]
    assert "traces" in top["missing_signals"]
    assert top["breakdown"]["log_evidence"]["available"] is False
    assert top["breakdown"]["log_evidence"]["weight"] == 0.0
    assert top["breakdown"]["trace_bottleneck"]["available"] is False
    assert top["breakdown"]["trace_bottleneck"]["weight"] == 0.0


def test_scenario_f_contradictory_signals_surface_conflict_and_recalculate(
    client: TestClient,
    db_session: Session,
):
    """Scenario F: Anomaly fires first on Order with 0 error logs & thin wrapper spans, while Payment owns error logs & origin 502 spans."""
    proj, order_svc, pay_svc, _ = _get_core_services(db_session)
    t0 = datetime(2026, 11, 10, 15, 0, 0, tzinfo=timezone.utc)

    # First evaluate with anomalies ONLY (Order earlier -> Order might look temporally ahead)
    _add_anomaly(db_session, proj.id, order_svc.id, "latency", 750.0, 80.0, 837.5, t0, "critical")
    _add_anomaly(db_session, proj.id, pay_svc.id, "error_rate", 95.0, 0.0, 950.0, t0 + timedelta(seconds=30), "high")
    db_session.commit()

    init_resp = client.post(
        "/api/v1/correlations/evaluate",
        json={
            "project_id": str(proj.id),
            "start_time": (t0 - timedelta(minutes=1)).isoformat(),
            "end_time": (t0 + timedelta(minutes=2)).isoformat(),
        },
    )
    assert init_resp.status_code == 200
    gid = init_resp.json()["groups"][0]["id"]

    # Now persist contradictory logs and trace spans proving Payment is the true fault origin
    for i in range(5):
        ts = t0 + timedelta(seconds=5 + i)
        tid = f"trace-contra-{i}"
        _add_log(db_session, proj.id, order_svc.id, ts, "INFO", "Handling checkout order request", trace_id=tid)
        _add_log(db_session, proj.id, pay_svc.id, ts, "ERROR", "Upstream payment ledger timeout 504", trace_id=tid, exception_type="TimeoutError")
        _add_span(db_session, proj.id, order_svc.id, tid, f"c-ord-{i}", None, "POST /orders", "server", ts, 760.0)
        _add_span(db_session, proj.id, pay_svc.id, tid, f"c-pay-{i}", f"c-ord-{i}", "POST /charge", "server", ts + timedelta(milliseconds=10), 740.0, status="error", http_status=504, error_message="Gateway timeout")
    db_session.commit()

    # Deterministic recalculation integrates newly persisted multi-signal telemetry
    recalc = client.post(f"/api/v1/correlations/{gid}/recalculate")
    assert recalc.status_code == 200
    updated_group = recalc.json()

    order_cand = next(c for c in updated_group["ranked_candidates"] if c["service_slug"] == "order-service")
    pay_cand = next(c for c in updated_group["ranked_candidates"] if c["service_slug"] == "payment-service")

    assert updated_group["ranked_candidates"][0]["service_slug"] == "payment-service"
    assert len(order_cand["contradictory_evidence"]) >= 1
    assert pay_cand["score"] > order_cand["score"]

    # Project isolation check (wrong X-Project-Id returns 403)
    iso_resp = client.get(
        f"/api/v1/correlations/{gid}/evidence",
        headers={"X-Project-Id": str(uuid4())},
    )
    assert iso_resp.status_code == 403
    assert client.get(f"/api/v1/correlations/{uuid4()}/evidence").status_code == 404
