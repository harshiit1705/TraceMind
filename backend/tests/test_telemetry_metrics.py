"""Tests for Sprint 6 Milestone 6.1: Metrics persistence, anomaly forwarding, overview, and stats APIs."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyEvent
from app.models.project import Project
from app.models.telemetry import MetricSample


def test_metrics_ingest_persist_and_forward_to_anomaly_engine(client: TestClient, db_session: Session):
    """Verify metric samples persist as raw time-series and trigger anomaly detection once warmed up."""
    proj = db_session.query(Project).first()
    assert proj is not None

    base_t = datetime.now(timezone.utc) - timedelta(seconds=30)

    # 1. Send 3 normal warmup latency samples + 1 request_count + 1 cpu_usage_pct
    warmup_samples = [
        {
            "service_identifier": "payment-service",
            "metric_name": "latency",
            "metric_unit": "ms",
            "value": 42.0 + i,
            "timestamp": (base_t + timedelta(seconds=i)).isoformat(),
            "endpoint": "POST /payments/charge",
            "http_status_code": 200,
            "request_id": f"req-w-{i}",
            "trace_id": "tr-warmup-001",
            "source_event_id": f"src-warmup-{i}",
        }
        for i in range(4)
    ]
    warmup_samples.append(
        {
            "service_identifier": "payment-service",
            "metric_name": "cpu_usage_pct",
            "metric_unit": "percent",
            "value": 18.5,
            "timestamp": (base_t + timedelta(seconds=5)).isoformat(),
            "evaluate_anomaly": False,
        }
    )

    resp = client.post(
        "/api/v1/telemetry/metrics",
        json={"project_id": str(proj.id), "samples": warmup_samples},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted_count"] == 5
    assert data["duplicate_count"] == 0
    assert data["anomalies_detected_count"] == 0

    # 2. Duplicate source_event_id is idempotently ignored
    dup_resp = client.post(
        "/api/v1/telemetry/metrics",
        json={"project_id": str(proj.id), "samples": [warmup_samples[0]]},
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["accepted_count"] == 0
    assert dup_resp.json()["duplicate_count"] == 1

    # 3. Spike sample -> persists MetricSample AND creates AnomalyEvent via AnomalyService
    spike_t = base_t + timedelta(seconds=10)
    spike_resp = client.post(
        "/api/v1/telemetry/metrics",
        json={
            "project_id": str(proj.id),
            "samples": [
                {
                    "service_identifier": "payment-service",
                    "metric_name": "latency",
                    "metric_unit": "ms",
                    "value": 850.0,
                    "timestamp": spike_t.isoformat(),
                    "endpoint": "POST /payments/charge",
                    "http_status_code": 200,
                    "request_id": "req-spike-1",
                    "trace_id": "tr-spike-999",
                    "source_event_id": "src-spike-1",
                }
            ],
        },
    )
    assert spike_resp.status_code == 200
    s_data = spike_resp.json()
    assert s_data["accepted_count"] == 1
    assert s_data["anomalies_detected_count"] == 1
    assert s_data["results"][0]["is_anomaly"] is True

    # Verify raw MetricSample rows & AnomalyEvent in DB
    persisted_samples = db_session.query(MetricSample).filter_by(trace_id="tr-spike-999").all()
    assert len(persisted_samples) == 1
    assert persisted_samples[0].endpoint == "POST /payments/charge"
    assert persisted_samples[0].http_status_code == 200

    anomalies = db_session.query(AnomalyEvent).filter_by(source_event_id="src-spike-1").all()
    assert len(anomalies) == 1

    # 4. Delayed/out-of-order historical sample still persists cleanly without failing batch
    delayed_t = base_t - timedelta(minutes=5)
    delayed_resp = client.post(
        "/api/v1/telemetry/metrics",
        json={
            "project_id": str(proj.id),
            "samples": [
                {
                    "service_identifier": "payment-service",
                    "metric_name": "latency",
                    "metric_unit": "ms",
                    "value": 55.0,
                    "timestamp": delayed_t.isoformat(),
                    "source_event_id": "src-delayed-1",
                }
            ],
        },
    )
    assert delayed_resp.status_code == 200
    d_data = delayed_resp.json()
    assert d_data["accepted_count"] == 1
    assert d_data["results"][0]["persisted"] is True
    assert d_data["results"][0]["anomaly_evaluated"] is False

    # 5. Query GET /api/v1/telemetry/metrics with filters
    list_resp = client.get(
        f"/api/v1/telemetry/metrics?project_id={proj.id}&service=payment-service&metric_name=latency"
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 6

    # 6. Overview endpoint returns non-empty time series computed from persisted samples
    ov_resp = client.get(f"/api/v1/telemetry/overview?range=15m&project_id={proj.id}")
    assert ov_resp.status_code == 200
    ov = ov_resp.json()
    assert len(ov["points"]) >= 1
    assert ov["currentP95Ms"] > 0

    # 7. Services stats & detail endpoints work cleanly
    stats_resp = client.get(f"/api/v1/services/stats?project_id={proj.id}")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["totalServices"] >= 1

    detail_resp = client.get("/api/v1/services/payment-service")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["slug"] == "payment-service"


def test_metrics_validation_rejects_invalid_values(client: TestClient, db_session: Session):
    proj = db_session.query(Project).first()
    # Negative latency rejected
    res_neg = client.post(
        "/api/v1/telemetry/metrics",
        json={
            "project_id": str(proj.id),
            "samples": [{"service_identifier": "order-service", "metric_name": "latency", "value": -10.0}],
        },
    )
    assert res_neg.status_code == 422

    # Error rate > 100 rejected
    res_err = client.post(
        "/api/v1/telemetry/metrics",
        json={
            "project_id": str(proj.id),
            "samples": [{"service_identifier": "order-service", "metric_name": "error_rate", "value": 150.0}],
        },
    )
    assert res_err.status_code == 422

    # Invalid HTTP status code rejected
    res_http = client.post(
        "/api/v1/telemetry/metrics",
        json={
            "project_id": str(proj.id),
            "samples": [
                {
                    "service_identifier": "order-service",
                    "metric_name": "latency",
                    "value": 20.0,
                    "http_status_code": 999,
                }
            ],
        },
    )
    assert res_http.status_code == 422


def test_telemetry_overview_returns_empty_series_for_empty_project(client: TestClient, db_session: Session):
    """Ensure overview never returns fabricated demo values when a project has zero metric samples."""
    proj_first = db_session.query(Project).first()
    empty_proj = Project(
        id=uuid4(),
        organization_id=proj_first.organization_id,
        slug=f"empty-proj-{uuid4().hex[:6]}",
        name="Empty Project",
    )
    db_session.add(empty_proj)
    db_session.commit()

    ov_resp = client.get(f"/api/v1/telemetry/overview?range=15m&project_id={empty_proj.id}")
    assert ov_resp.status_code == 200
    data = ov_resp.json()
    assert data["points"] == []
    assert data["currentThroughputRps"] == 0.0
    assert data["currentP95Ms"] == 0.0
    assert data["throughputAvailable"] is False
    assert data["requestRateStatus"] == "no_traffic"
    assert data["totalRequests"] == 0
    assert data["sampleIngestionRatePerSec"] is None


def test_request_rate_and_services_stats_semantics_deterministic(client: TestClient, db_session: Session):
    """Verify exact request-rate calculations, multi-service sums, telemetry vs request isolation,
    insufficient-data states, and that /services/stats never leaks seeded mock RPS values."""
    proj_first = db_session.query(Project).first()
    assert proj_first is not None

    # 0. Even on the default seeded project before any live samples, /services/stats must NOT report 90k+ seeded RPS
    default_stats = client.get(f"/api/v1/services/stats?project_id={proj_first.id}")
    assert default_stats.status_code == 200
    d_stats = default_stats.json()
    assert d_stats["sampleIngestionRatePerSec"] is None
    assert "93883" not in d_stats["ingestionBandwidth"]
    assert "samples/s" in d_stats["ingestionBandwidth"]
    assert d_stats["applicationRequestRateRps"] is None
    assert d_stats["requestRateStatus"] == "no_traffic"

    # Create an isolated project + two services to test clean metrics math
    from app.models.service import Service
    test_proj = Project(
        id=uuid4(),
        organization_id=proj_first.organization_id,
        slug=f"metrics-sem-{uuid4().hex[:6]}",
        name="Metrics Semantics Project",
    )
    svc_order = Service(
        id=uuid4(),
        project_id=test_proj.id,
        slug="order-service",
        name="Order Service",
        identifier="svc:order",
        tier=0,
        status="healthy",
        request_rate_rps=99999.0,  # seeded/legacy placeholder that must NOT leak into /services/stats ingestion
    )
    svc_pay = Service(
        id=uuid4(),
        project_id=test_proj.id,
        slug="payment-service",
        name="Payment Service",
        identifier="svc:payment",
        tier=0,
        status="healthy",
    )
    db_session.add_all([test_proj, svc_order, svc_pay])
    db_session.commit()

    now = datetime.now(timezone.utc)

    # 1. No application traffic: only cpu_usage_pct and memory_usage_mb ingested
    t_sys_base = now - timedelta(minutes=5)
    res_sys = client.post(
        "/api/v1/telemetry/metrics",
        json={
            "project_id": str(test_proj.id),
            "samples": [
                {
                    "service_identifier": "order-service",
                    "metric_name": "cpu_usage_pct",
                    "metric_unit": "percent",
                    "value": 24.5,
                    "timestamp": t_sys_base.isoformat(),
                    "evaluate_anomaly": False,
                },
                {
                    "service_identifier": "order-service",
                    "metric_name": "memory_usage_mb",
                    "metric_unit": "mb",
                    "value": 128.0,
                    "timestamp": (t_sys_base + timedelta(seconds=10)).isoformat(),
                    "evaluate_anomaly": False,
                },
            ],
        },
    )
    assert res_sys.status_code == 200
    ov_sys = client.get(f"/api/v1/telemetry/overview?range=15m&project_id={test_proj.id}").json()
    assert ov_sys["totalMetricSamples"] == 2
    assert ov_sys["totalRequests"] == 0
    assert ov_sys["requestRateStatus"] == "no_traffic"
    assert ov_sys["throughputAvailable"] is False
    assert ov_sys["sampleIngestionRatePerSec"] == 0.2  # 2 samples / 10.0s span

    # 2. Single latency point without request_rate/window_seconds -> insufficient_data (no fabricated spike)
    res_single = client.post(
        "/api/v1/telemetry/metrics",
        json={
            "project_id": str(test_proj.id),
            "samples": [
                {
                    "service_identifier": "payment-service",
                    "metric_name": "latency",
                    "metric_unit": "ms",
                    "value": 110.0,
                    "timestamp": (now - timedelta(minutes=3)).isoformat(),
                }
            ],
        },
    )
    assert res_single.status_code == 200
    ov_insuff = client.get(f"/api/v1/telemetry/overview?range=15m&project_id={test_proj.id}").json()
    assert ov_insuff["totalRequests"] == 1
    assert ov_insuff["requestRateStatus"] == "insufficient_data"
    assert ov_insuff["throughputAvailable"] is False
    assert ov_insuff["currentThroughputRps"] is None

    # 3. Known request counts over known time windows across TWO services (latest bucket):
    # - order-service: 60 requests over 10.0s = 6.0 req/s (25% error rate on batch)
    # - payment-service: 30 requests over 10.0s = 3.0 req/s (0% error rate on batch)
    # Total active application request rate across both services = 9.0 req/s; total new requests = 90
    bucket_t = now.replace(second=30, microsecond=0) - timedelta(minutes=1)
    res_multi = client.post(
        "/api/v1/telemetry/metrics",
        json={
            "project_id": str(test_proj.id),
            "samples": [
                {
                    "service_identifier": "order-service",
                    "metric_name": "request_count",
                    "metric_unit": "count",
                    "value": 60.0,
                    "timestamp": bucket_t.isoformat(),
                    "attributes": {"window_seconds": 10.0},
                    "evaluate_anomaly": False,
                },
                {
                    "service_identifier": "order-service",
                    "metric_name": "error_rate",
                    "metric_unit": "percent",
                    "value": 25.0,
                    "timestamp": (bucket_t + timedelta(seconds=1)).isoformat(),
                    "attributes": {"request_count": 60, "window_seconds": 10.0},
                    "evaluate_anomaly": False,
                },
                {
                    "service_identifier": "payment-service",
                    "metric_name": "request_count",
                    "metric_unit": "count",
                    "value": 30.0,
                    "timestamp": (bucket_t + timedelta(seconds=2)).isoformat(),
                    "attributes": {"window_seconds": 10.0},
                    "evaluate_anomaly": False,
                },
                {
                    "service_identifier": "payment-service",
                    "metric_name": "error_rate",
                    "metric_unit": "percent",
                    "value": 0.0,
                    "timestamp": (bucket_t + timedelta(seconds=3)).isoformat(),
                    "attributes": {"request_count": 30, "window_seconds": 10.0},
                    "evaluate_anomaly": False,
                },
            ],
        },
    )
    assert res_multi.status_code == 200
    ov_full = client.get(f"/api/v1/telemetry/overview?range=15m&project_id={test_proj.id}").json()
    assert ov_full["requestRateStatus"] == "available"
    assert ov_full["throughputAvailable"] is True
    assert ov_full["currentThroughputRps"] == 9.0  # 6.0 + 3.0 req/s (never 99999!)
    assert ov_full["totalRequests"] == 91  # 1 prior latency req + 60 + 30
    # Weighted error rate in latest bucket: (25*60 + 0*30) / (60 + 30) = 16.67%
    latest_pt = ov_full["points"][-1]
    assert latest_pt["errorRatePercent"] == 16.67

    # 4. /services/stats agrees with real telemetry ingestion & application req/s without fake 99999 rps
    stats_full = client.get(f"/api/v1/services/stats?project_id={test_proj.id}").json()
    assert stats_full["totalMetricSamples"] == 7
    assert "99999" not in stats_full["ingestionBandwidth"]
    assert "samples/s" in stats_full["ingestionBandwidth"]
    assert stats_full["applicationRequestRateRps"] == 9.0
    assert stats_full["totalRequests"] == 91


def test_reconciled_api_endpoints_topology_incidents_logs(client: TestClient, db_session: Session):
    """Verify dependency graph, service detail, incident stats, and incident logs API contracts."""
    proj = db_session.query(Project).first()
    assert proj is not None

    graph_resp = client.get(f"/api/v1/dependencies/graph?project_id={proj.id}")
    assert graph_resp.status_code == 200
    graph = graph_resp.json()
    assert len(graph["nodes"]) >= 3
    assert len(graph["edges"]) >= 2

    inc_stats = client.get(f"/api/v1/incidents/stats?project_id={proj.id}")
    assert inc_stats.status_code == 200
    for key in ("activeCount", "criticalImpactCount", "acknowledgedCount", "resolved24hCount", "mttdFormatted", "mttrFormatted"):
        assert key in inc_stats.json()

    missing_svc = client.get("/api/v1/services/nonexistent-svc-xyz")
    assert missing_svc.status_code == 404

    missing_inc_logs = client.get("/api/v1/incidents/INC-DOES-NOT-EXIST/logs")
    assert missing_inc_logs.status_code == 404


