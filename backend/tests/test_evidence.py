from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.services.incident_service import IncidentService


def test_get_evidence_for_inc_8492(client: TestClient):
    response = client.get("/api/v1/incidents/INC-8492/evidence")
    assert response.status_code == 200
    data = response.json()
    assert data["incident_number"] == "INC-8492"
    assert data["total_count"] >= 4
    assert len(data["items"]) >= 4

    # Verify presence of metric, log, trace, and topology evidence
    evidence_types = {e["evidence_type"] for e in data["items"]}
    assert "metric" in evidence_types
    assert "log" in evidence_types
    assert "trace" in evidence_types
    assert "topology" in evidence_types

    # Verify stable evidence keys are populated
    evidence_keys = {e["evidence_key"] for e in data["items"]}
    assert "ev-101-db-pool" in evidence_keys
    assert "ev-102-payment-latency" in evidence_keys
    assert "ev-103-order-latency" in evidence_keys
    assert "ev-104-gateway-504" in evidence_keys
    assert "ev-105-lock-log" in evidence_keys
    assert "ev-106-topology-cascade" in evidence_keys

    # Find the Aurora connection pool metric evidence
    pool_evidence = next(
        e for e in data["items"]
        if e["evidence_type"] == "metric" and "aurora" in e["service_identifier"]
    )
    assert pool_evidence["evidence_key"] == "ev-101-db-pool"
    assert pool_evidence["confidence_weight"] == 0.99
    assert pool_evidence["payload"]["current_value"] == 980
    assert pool_evidence["payload"]["max_connections_limit"] == 1000
    assert pool_evidence["payload"]["saturation_percent"] == 98.0

    # Find Payment Service metric evidence (P99 1,420ms, 8.85% err)
    payment_evidence = next(
        e for e in data["items"]
        if e["evidence_type"] == "metric" and "stripe-ledger" in e["service_identifier"]
    )
    assert payment_evidence["evidence_key"] == "ev-102-payment-latency"
    assert payment_evidence["payload"]["p99_latency_ms"] == 1420.0
    assert payment_evidence["payload"]["error_rate_percent"] == 8.85

    # Find Order Service metric evidence (P99 840ms, 4.12% err)
    order_evidence = next(
        e for e in data["items"]
        if e["evidence_type"] == "metric" and "order-orchestration" in e["service_identifier"]
    )
    assert order_evidence["evidence_key"] == "ev-103-order-latency"
    assert order_evidence["payload"]["p99_latency_ms"] == 840.0
    assert order_evidence["payload"]["error_rate_percent"] == 4.12

    # Find Gateway trace evidence (2.84% err, 504 status)
    gateway_evidence = next(
        e for e in data["items"]
        if e["evidence_type"] == "trace" and "ingress-proxy" in e["service_identifier"]
    )
    assert gateway_evidence["evidence_key"] == "ev-104-gateway-504"
    assert gateway_evidence["payload"]["status_code"] == 504
    assert gateway_evidence["payload"]["error_rate_percent"] == 2.84

    # Find the Topology evidence verifying failure propagation path
    topo_evidence = next(
        e for e in data["items"]
        if e["evidence_type"] == "topology"
    )
    assert topo_evidence["evidence_key"] == "ev-106-topology-cascade"
    assert topo_evidence["payload"]["propagation_depth_hops"] == 3
    assert topo_evidence["payload"]["cascade_latency_added_ms"] == 806.0
    assert len(topo_evidence["payload"]["propagation_path"]) == 4


def test_get_evidence_nonexistent_incident(client: TestClient):
    response = client.get("/api/v1/incidents/INC-NONEXISTENT/evidence")
    assert response.status_code == 404


def test_finding_supporting_evidence_reference_resolution(client: TestClient, db_session: Session):
    """Proves that all supporting_evidence_ids referenced in investigation findings resolve to actual evidence items."""
    # 1. Fetch evidence items for INC-8492
    ev_response = client.get("/api/v1/incidents/INC-8492/evidence")
    assert ev_response.status_code == 200
    ev_data = ev_response.json()
    evidence_items = ev_data["items"]

    # Index evidence by evidence_key and by stringified UUID
    evidence_by_key = {e["evidence_key"]: e for e in evidence_items if e.get("evidence_key")}
    evidence_by_id = {e["id"]: e for e in evidence_items}

    # 2. Fetch the investigation for INC-8492
    svc = IncidentService(db_session)
    investigation = svc.get_investigation_for_incident("INC-8492")
    assert investigation is not None
    assert len(investigation.findings) > 0

    # 3. Verify every supporting evidence reference resolves
    for finding in investigation.findings:
        assert len(finding.supporting_evidence_ids) > 0
        for ref_id in finding.supporting_evidence_ids:
            resolved_evidence = evidence_by_key.get(ref_id) or evidence_by_id.get(ref_id)
            assert resolved_evidence is not None, f"Finding '{finding.title}' referenced unresolvable evidence ID: {ref_id}"
            assert "title" in resolved_evidence
            assert "payload" in resolved_evidence

    # Specifically check the confirmed root cause finding
    root_cause_finding = next(f for f in investigation.findings if f.status == "CONFIRMED")
    assert "ev-101-db-pool" in root_cause_finding.supporting_evidence_ids
    assert "ev-105-lock-log" in root_cause_finding.supporting_evidence_ids

    pool_ev = evidence_by_key["ev-101-db-pool"]
    assert pool_ev["payload"]["saturation_percent"] == 98.0

    log_ev = evidence_by_key["ev-105-lock-log"]
    assert "RowExclusiveLock" in log_ev["payload"]["lock_type"]
