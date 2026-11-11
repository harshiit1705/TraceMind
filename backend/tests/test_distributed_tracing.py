"""Tests for Sprint 6 Milestone 6.3: Distributed span ingestion, waterfall ordering, and validation."""

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.telemetry import TraceSpan


def test_trace_spans_ingest_waterfall_and_bottleneck_detection(client: TestClient, db_session: Session):
    """Verify multi-service spans reconstruct parent-child depth, waterfall offsets, and bottlenecks."""
    proj = db_session.query(Project).first()
    assert proj is not None

    t0 = datetime.now(timezone.utc) - timedelta(seconds=10)
    trace_id = "tr-e2e-waterfall-0001"

    spans = [
        {
            "service_identifier": "order-service",
            "trace_id": trace_id,
            "span_id": "sp-root-1",
            "parent_span_id": None,
            "operation_name": "POST /orders",
            "span_kind": "server",
            "start_time": t0.isoformat(),
            "end_time": (t0 + timedelta(milliseconds=820)).isoformat(),
            "duration_ms": 820.0,
            "status": "ok",
            "http_status_code": 201,
            "request_id": "req-tr-1",
            "attributes": {
                "authorization": "Bearer secret-jwt-should-be-scrubbed",
                "cookie": "session=abc",
                "http.method": "POST",
            },
        },
        {
            "service_identifier": "order-service",
            "trace_id": trace_id,
            "span_id": "sp-cli-inv",
            "parent_span_id": "sp-root-1",
            "operation_name": "HTTP POST inventory-service /inventory/reserve",
            "span_kind": "client",
            "start_time": (t0 + timedelta(milliseconds=5)).isoformat(),
            "end_time": (t0 + timedelta(milliseconds=35)).isoformat(),
            "duration_ms": 30.0,
            "status": "ok",
            "http_status_code": 200,
        },
        {
            "service_identifier": "inventory-service",
            "trace_id": trace_id,
            "span_id": "sp-srv-inv",
            "parent_span_id": "sp-cli-inv",
            "operation_name": "POST /inventory/reserve",
            "span_kind": "server",
            "start_time": (t0 + timedelta(milliseconds=7)).isoformat(),
            "end_time": (t0 + timedelta(milliseconds=32)).isoformat(),
            "duration_ms": 25.0,
            "status": "ok",
            "http_status_code": 200,
        },
        {
            "service_identifier": "order-service",
            "trace_id": trace_id,
            "span_id": "sp-cli-pay",
            "parent_span_id": "sp-root-1",
            "operation_name": "HTTP POST payment-service /payments/charge",
            "span_kind": "client",
            "start_time": (t0 + timedelta(milliseconds=40)).isoformat(),
            "end_time": (t0 + timedelta(milliseconds=815)).isoformat(),
            "duration_ms": 775.0,
            "status": "ok",
            "http_status_code": 200,
        },
        {
            "service_identifier": "payment-service",
            "trace_id": trace_id,
            "span_id": "sp-srv-pay",
            "parent_span_id": "sp-cli-pay",
            "operation_name": "POST /payments/charge",
            "span_kind": "server",
            "start_time": (t0 + timedelta(milliseconds=42)).isoformat(),
            "end_time": (t0 + timedelta(milliseconds=812)).isoformat(),
            "duration_ms": 770.0,
            "status": "ok",
            "http_status_code": 200,
        },
        {
            "service_identifier": "payment-service",
            "trace_id": trace_id,
            "span_id": "sp-int-pay",
            "parent_span_id": "sp-srv-pay",
            "operation_name": "payment.gateway_charge",
            "span_kind": "internal",
            "start_time": (t0 + timedelta(milliseconds=45)).isoformat(),
            "end_time": (t0 + timedelta(milliseconds=810)).isoformat(),
            "duration_ms": 765.0,
            "status": "ok",
        },
    ]

    resp = client.post("/api/v1/telemetry/spans", json={"project_id": str(proj.id), "spans": spans})
    assert resp.status_code == 200
    assert resp.json()["accepted_count"] == 6
    assert resp.json()["duplicate_count"] == 0

    # Verify secret attributes scrubbed in DB
    root_row = db_session.query(TraceSpan).filter_by(trace_id=trace_id, span_id="sp-root-1").one()
    assert root_row.attributes_json["authorization"] == "[REDACTED]"
    assert root_row.attributes_json["cookie"] == "[REDACTED]"
    assert root_row.attributes_json["http.method"] == "POST"

    # Duplicate span idempotency
    dup = client.post("/api/v1/telemetry/spans", json={"project_id": str(proj.id), "spans": [spans[0]]})
    assert dup.status_code == 200
    assert dup.json()["accepted_count"] == 0
    assert dup.json()["duplicate_count"] == 1

    # List traces
    list_res = client.get(f"/api/v1/traces?project_id={proj.id}&service=payment-service")
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert len(items) >= 1
    match = next(t for t in items if t["id"] == trace_id)
    assert match["rootServiceSlug"] == "order-service"
    assert match["spansCount"] == 6
    assert match["anomalous"] is True
    assert match["durationMs"] >= 820.0

    # Retrieve detailed waterfall
    detail_res = client.get(f"/api/v1/traces/{trace_id}")
    assert detail_res.status_code == 200
    wf = detail_res.json()["spans"]
    assert len(wf) == 6
    # Verify depths: root (0) -> client (1) -> server (2) -> internal (3)
    depth_map = {s["span_id"]: s["depth"] for s in wf}
    assert depth_map["sp-root-1"] == 0
    assert depth_map["sp-cli-pay"] == 1
    assert depth_map["sp-srv-pay"] == 2
    assert depth_map["sp-int-pay"] == 3
    # Verify bottleneck highlighted on slowest downstream client/server/internal span
    assert any(s["isBottleneck"] for s in wf)


def test_trace_span_validation_rejects_cycles_and_negative_durations(client: TestClient, db_session: Session):
    proj = db_session.query(Project).first()
    now = datetime.now(timezone.utc)

    # Self-cycle parent_span_id == span_id
    res_cycle = client.post(
        "/api/v1/telemetry/spans",
        json={
            "project_id": str(proj.id),
            "spans": [
                {
                    "service_identifier": "order-service",
                    "trace_id": "tr-invalid-001",
                    "span_id": "sp-loop",
                    "parent_span_id": "sp-loop",
                    "operation_name": "POST /orders",
                    "start_time": now.isoformat(),
                    "end_time": (now + timedelta(milliseconds=10)).isoformat(),
                }
            ],
        },
    )
    assert res_cycle.status_code == 422

    # end_time < start_time
    res_time = client.post(
        "/api/v1/telemetry/spans",
        json={
            "project_id": str(proj.id),
            "spans": [
                {
                    "service_identifier": "order-service",
                    "trace_id": "tr-invalid-002",
                    "span_id": "sp-rev",
                    "operation_name": "POST /orders",
                    "start_time": now.isoformat(),
                    "end_time": (now - timedelta(milliseconds=10)).isoformat(),
                }
            ],
        },
    )
    assert res_time.status_code == 422

