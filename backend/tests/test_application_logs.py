"""Tests for Sprint 6 Milestone 6.2: Structured logging ingestion, redaction, filtering, and incident logs."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.project import Project
from app.models.telemetry import ApplicationLog


def test_logs_ingest_secret_redaction_and_filtering(client: TestClient, db_session: Session):
    """Verify structured logs persist with secret redaction and support multi-field filtering + pagination."""
    proj = db_session.query(Project).first()
    assert proj is not None
    now = datetime.now(timezone.utc)

    payload = {
        "project_id": str(proj.id),
        "logs": [
            {
                "service_identifier": "payment-service",
                "timestamp": (now - timedelta(seconds=10)).isoformat(),
                "level": "WARN",  # Normalized to WARNING
                "message": "Slow downstream auth Bearer sk-secretkey1234567890abcdef and postgresql://admin:superpass@db:5432/prod",
                "request_id": "req-log-1",
                "trace_id": "tr-log-abc12345",
                "span_id": "sp-0001",
                "source_event_id": "log-src-1",
                "attributes": {
                    "endpoint": "POST /payments/charge",
                    "authorization": "Bearer secret-header-token-should-redact",
                    "api_key": "AIzaSySecretKey1234567890123456789012345",
                    "order_id": "ord-123",
                },
            },
            {
                "service_identifier": "order-service",
                "timestamp": now.isoformat(),
                "level": "ERROR",
                "message": "Payment gateway timeout for order ord-123",
                "request_id": "req-log-1",
                "trace_id": "tr-log-abc12345",
                "span_id": "sp-0002",
                "exception_type": "GatewayTimeout",
                "exception_message": "Upstream error password=my_secret_pwd",
            },
        ],
    }

    resp = client.post("/api/v1/telemetry/logs", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted_count"] == 2
    assert data["duplicate_count"] == 0

    # Verify DB secret redaction
    rows = db_session.query(ApplicationLog).filter_by(trace_id="tr-log-abc12345").all()
    assert len(rows) == 2
    pay_log = next(r for r in rows if r.level == "WARNING")
    assert "superpass" not in pay_log.message
    assert "sk-secretkey" not in pay_log.message
    assert "[REDACTED_PASSWORD]" in pay_log.message
    assert pay_log.attributes_json["authorization"] == "[REDACTED]"
    assert pay_log.attributes_json["api_key"] == "[REDACTED]"
    assert pay_log.attributes_json["order_id"] == "ord-123"

    err_log = next(r for r in rows if r.level == "ERROR")
    assert "my_secret_pwd" not in (err_log.exception_message or "")

    # Duplicate check
    dup_resp = client.post(
        "/api/v1/telemetry/logs",
        json={"project_id": str(proj.id), "logs": [payload["logs"][0]]},
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["accepted_count"] == 0
    assert dup_resp.json()["duplicate_count"] == 1

    # Query filtering by trace_id, level, service, search
    by_trace = client.get(f"/api/v1/logs?project_id={proj.id}&trace_id=tr-log-abc12345")
    assert by_trace.status_code == 200
    assert by_trace.json()["total"] == 2

    by_level = client.get(f"/api/v1/logs?project_id={proj.id}&trace_id=tr-log-abc12345&level=ERROR")
    assert by_level.status_code == 200
    assert by_level.json()["total"] == 1
    assert by_level.json()["items"][0]["service_slug"] == "order-service"

    by_search = client.get(f"/api/v1/logs?project_id={proj.id}&search=ord-123")
    assert by_search.status_code == 200
    assert by_search.json()["total"] >= 1


def test_incident_logs_retrieval_and_batch_limits(client: TestClient, db_session: Session):
    """Verify GET /incidents/{id}/logs retrieves incident-scoped logs and batch cap is enforced."""
    proj = db_session.query(Project).first()
    now = datetime.now(timezone.utc)

    # Create an incident affecting Payment Service
    inc = Incident(
        id=uuid4(),
        project_id=proj.id,
        incident_number="INC-LOG-TEST",
        title="Payment Latency Incident",
        severity="HIGH",
        status="DETECTED",
        started_at=now - timedelta(minutes=2),
        affected_services=["Payment Service"],
        is_demo=False,
    )
    db_session.add(inc)
    db_session.commit()

    # Ingest a Payment Service log in timeframe
    client.post(
        "/api/v1/telemetry/logs",
        json={
            "project_id": str(proj.id),
            "logs": [
                {
                    "service_identifier": "payment-service",
                    "timestamp": now.isoformat(),
                    "level": "ERROR",
                    "message": "Settlement thread stalled waiting on upstream",
                    "trace_id": "tr-inc-log-01",
                }
            ],
        },
    )

    inc_logs = client.get(f"/api/v1/incidents/{inc.id}/logs")
    assert inc_logs.status_code == 200
    assert inc_logs.json()["total"] >= 1
    assert any("Settlement thread stalled" in item["message"] for item in inc_logs.json()["items"])

    # Oversized batch (>100) rejected with 422
    too_many = [
        {"service_identifier": "order-service", "level": "INFO", "message": f"msg {i}"}
        for i in range(101)
    ]
    res_over = client.post("/api/v1/telemetry/logs", json={"project_id": str(proj.id), "logs": too_many})
    assert res_over.status_code == 422

    # Incidents stats endpoint
    stats_res = client.get(f"/api/v1/incidents/stats?project_id={proj.id}")
    assert stats_res.status_code == 200
    assert stats_res.json()["activeCount"] >= 1

