"""Comprehensive test suite for Sprint 3: PostgreSQL Persistence for Anomaly Detection."""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.service import Service
from app.schemas.anomaly import (
    AnomalyDetectionConfig,
    AnomalyEvaluationRequest,
    DetectionMethod,
    DetectionStatus,
)
from app.services.anomaly.baseline import EWMABaseline, RollingBaseline
from app.services.anomaly.detector import AnomalyDetector
from app.services.anomaly.registry import get_anomaly_registry
from app.services.anomaly.service import AnomalyService
from tests.conftest import TestingSessionLocal


def test_baseline_persistence_survives_registry_reset(client: TestClient, db_session: Session):
    """Scenario 1: Baseline survives backend restart/registry reset and resumes seamlessly."""
    # 1. Fetch test project and service
    proj_resp = client.get("/api/v1/projects")
    project_id = UUID(proj_resp.json()[0]["id"])
    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    service = svc_resp.json()[0]
    service_id = service["identifier"]

    base_time = datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)

    # 2. Warm up baseline with 4 normal measurements (min_samples=3)
    for i in range(4):
        t = base_time + timedelta(seconds=i * 10)
        res = client.post(
            "/api/v1/anomalies/evaluate",
            json={
                "project_id": str(project_id),
                "service_identifier": service_id,
                "metric_name": "latency",
                "observed_value": 100.0,
                "timestamp": t.isoformat(),
            },
        )
        assert res.status_code == 200

    # Verify baseline is stored in database
    db_baseline = (
        db_session.query(AnomalyBaseline)
        .filter(
            AnomalyBaseline.project_id == project_id,
            AnomalyBaseline.metric_name == "latency",
        )
        .first()
    )
    assert db_baseline is not None
    assert db_baseline.sample_count >= 3
    assert db_baseline.version >= 4
    assert db_baseline.last_event_timestamp is not None

    # 3. Simulate backend restart: completely reset in-memory registry
    get_anomaly_registry().reset_all()
    assert get_anomaly_registry().count() == 0

    # 4. Next evaluation request after restart
    t_next = base_time + timedelta(seconds=50)
    res_after = client.post(
        "/api/v1/anomalies/evaluate",
        json={
            "project_id": str(project_id),
            "service_identifier": service_id,
            "metric_name": "latency",
            "observed_value": 102.0,
            "timestamp": t_next.isoformat(),
        },
    )
    assert res_after.status_code == 200
    data = res_after.json()
    # It must NOT be in WARMING_UP! It must resume from restored baseline
    assert data["detection_status"] == "NORMAL"
    assert data["is_anomaly"] is False
    assert data["expected_baseline"] == 100.0
    assert data["sample_count"] >= 3


def test_algorithm_state_restoration_rolling_average():
    """Scenario 2A: Rolling average restoration preserves exact sample window and subsequent calculations."""
    config = AnomalyDetectionConfig(
        method=DetectionMethod.ROLLING_AVERAGE,
        window_size=4,
        min_samples=2,
        threshold_pct=30.0,
    )
    original_detector = AnomalyDetector(config=config)
    t0 = datetime(2026, 11, 5, 8, 0, 0, tzinfo=timezone.utc)

    # Ingest 3 consistent normal measurements around 100.0
    for i, val in enumerate([100.0, 100.0, 100.0]):
        original_detector.evaluate_and_update(
            "latency", val, update_if_normal=True, timestamp=t0 + timedelta(seconds=i)
        )

    assert original_detector.get_baseline_value("latency") == 100.0
    state_snapshot = original_detector.export_state("latency")
    watermark = original_detector.get_last_timestamp("latency")

    # Restore in a fresh detector
    restored_detector = AnomalyDetector(config=config)
    restored_detector.restore_state("latency", state_snapshot, last_timestamp=watermark)

    assert restored_detector.get_baseline_value("latency") == 100.0
    assert restored_detector.get_sample_count("latency") == 3

    # Submit identical 4th and 5th measurements to both and compare
    t_subseq1 = t0 + timedelta(seconds=10)
    res_orig = original_detector.evaluate_and_update("latency", 102.0, timestamp=t_subseq1)
    res_rest = restored_detector.evaluate_and_update("latency", 102.0, timestamp=t_subseq1)

    assert res_orig.expected_baseline == res_rest.expected_baseline
    assert res_orig.is_anomaly == res_rest.is_anomaly

    # 5th measurement exceeds window size 4 (first 100 evicted)
    t_subseq2 = t0 + timedelta(seconds=20)
    res_orig2 = original_detector.evaluate_and_update("latency", 104.0, timestamp=t_subseq2)
    res_rest2 = restored_detector.evaluate_and_update("latency", 104.0, timestamp=t_subseq2)

    assert res_orig2.expected_baseline == res_rest2.expected_baseline
    assert res_orig2.observed_value == res_rest2.observed_value


def test_algorithm_state_restoration_ewma():
    """Scenario 2B: EWMA restoration preserves exact internal smoothed estimate and weights."""
    config = AnomalyDetectionConfig(
        method=DetectionMethod.EWMA,
        alpha=0.4,
        min_samples=2,
    )
    orig = AnomalyDetector(config=config)
    t0 = datetime(2026, 11, 5, 8, 0, 0, tzinfo=timezone.utc)

    # Ingest 3 measurements: 100, 120, 140
    for i, v in enumerate([100.0, 120.0, 140.0]):
        orig.evaluate_and_update("latency", v, timestamp=t0 + timedelta(seconds=i))

    expected_val = orig.get_baseline_value("latency")
    snapshot = orig.export_state("latency")
    watermark = orig.get_last_timestamp("latency")

    restored = AnomalyDetector(config=config)
    restored.restore_state("latency", snapshot, last_timestamp=watermark)

    assert restored.get_baseline_value("latency") == expected_val
    assert restored.get_sample_count("latency") == 3

    # Subsequent measurement produces identical result
    t_next = t0 + timedelta(seconds=10)
    r1 = orig.evaluate_and_update("latency", 130.0, timestamp=t_next)
    r2 = restored.evaluate_and_update("latency", 130.0, timestamp=t_next)

    assert r1.expected_baseline == r2.expected_baseline
    assert r1.deviation_pct == r2.deviation_pct
    assert r1.is_anomaly == r2.is_anomaly


def test_algorithm_state_restoration_warmup():
    """Scenario 2C: Warmup candidate state is preserved across restarts."""
    config = AnomalyDetectionConfig(min_samples=4)
    orig = AnomalyDetector(config=config)
    t0 = datetime(2026, 11, 5, 8, 0, 0, tzinfo=timezone.utc)

    # Ingest only 2 of 4 required warmup samples
    orig.evaluate_and_update("latency", 50.0, timestamp=t0)
    orig.evaluate_and_update("latency", 52.0, timestamp=t0 + timedelta(seconds=1))

    assert orig.get_sample_count("latency") == 2
    assert orig.get_baseline_value("latency") is None  # Still warming up

    snapshot = orig.export_state("latency")
    watermark = orig.get_last_timestamp("latency")

    restored = AnomalyDetector(config=config)
    restored.restore_state("latency", snapshot, last_timestamp=watermark)

    assert restored.get_sample_count("latency") == 2
    assert restored.get_baseline_value("latency") is None

    # Next candidate continues warmup progress
    r = restored.evaluate_and_update("latency", 51.0, timestamp=t0 + timedelta(seconds=2))
    assert r.detection_status == DetectionStatus.WARMING_UP
    assert restored.get_sample_count("latency") == 3


def test_anomaly_event_persistence_and_anti_contamination(client: TestClient, db_session: Session):
    """Scenario 3: Confirmed anomalies are durably persisted without contaminating normal baseline."""
    proj_resp = client.get("/api/v1/projects")
    project_id = UUID(proj_resp.json()[0]["id"])
    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    service = svc_resp.json()[0]
    service_id = service["identifier"]

    t0 = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Warm up baseline around 100.0 ms
    for i in range(4):
        client.post(
            "/api/v1/anomalies/evaluate",
            json={
                "project_id": str(project_id),
                "service_identifier": service_id,
                "metric_name": "latency",
                "observed_value": 100.0,
                "timestamp": (t0 + timedelta(seconds=i * 5)).isoformat(),
            },
        )

    # Check baseline in DB before spike
    baseline_before = (
        db_session.query(AnomalyBaseline)
        .filter(AnomalyBaseline.project_id == project_id, AnomalyBaseline.metric_name == "latency")
        .first()
    )
    baseline_before_val = baseline_before.baseline_state["baseline"]["samples"]
    version_before = baseline_before.version

    # 2. Trigger critical anomaly: 350.0 ms (+250% spike)
    spike_time = t0 + timedelta(seconds=30)
    spike_resp = client.post(
        "/api/v1/anomalies/evaluate",
        json={
            "project_id": str(project_id),
            "service_identifier": service_id,
            "metric_name": "latency",
            "observed_value": 350.0,
            "timestamp": spike_time.isoformat(),
        },
    )
    assert spike_resp.status_code == 200
    spike_data = spike_resp.json()
    assert spike_data["is_anomaly"] is True
    assert spike_data["detection_status"] == "ANOMALY"

    # 3. Verify AnomalyEvent is durably stored in DB
    db_session.expire_all()
    events = (
        db_session.query(AnomalyEvent)
        .filter(
            AnomalyEvent.project_id == project_id,
            AnomalyEvent.metric_name == "latency",
        )
        .all()
    )
    assert len(events) == 1
    event = events[0]
    assert event.observed_value == 350.0
    assert event.expected_baseline == 100.0
    assert event.severity in ("HIGH", "CRITICAL")
    assert event.status == "OPEN"
    event_time = event.occurred_at if event.occurred_at.tzinfo else event.occurred_at.replace(tzinfo=timezone.utc)
    assert event_time == spike_time

    # 4. Anti-contamination verification: baseline in DB was NOT contaminated by 350.0
    baseline_after = (
        db_session.query(AnomalyBaseline)
        .filter(AnomalyBaseline.project_id == project_id, AnomalyBaseline.metric_name == "latency")
        .first()
    )
    assert 350.0 not in baseline_after.baseline_state["baseline"]["samples"]
    assert baseline_after.version == version_before + 1
    assert baseline_after.sample_count == baseline_before.sample_count
    after_watermark = (
        baseline_after.last_event_timestamp
        if baseline_after.last_event_timestamp.tzinfo
        else baseline_after.last_event_timestamp.replace(tzinfo=timezone.utc)
    )
    assert after_watermark == spike_time

    # 5. Out-of-order rejection verification: an older timestamp after anomaly must be rejected
    res_older = client.post(
        "/api/v1/anomalies/evaluate",
        json={
            "project_id": str(project_id),
            "service_identifier": service_id,
            "metric_name": "latency",
            "observed_value": 100.0,
            "timestamp": (spike_time - timedelta(seconds=1)).isoformat(),
        },
    )
    assert res_older.status_code == 409

    # 6. Detector restoration preserves the anomaly watermark across restarts
    get_anomaly_registry().reset_all()
    res_older_after_restart = client.post(
        "/api/v1/anomalies/evaluate",
        json={
            "project_id": str(project_id),
            "service_identifier": service_id,
            "metric_name": "latency",
            "observed_value": 100.0,
            "timestamp": (spike_time - timedelta(seconds=1)).isoformat(),
        },
    )
    assert res_older_after_restart.status_code == 409


def test_measurement_idempotency_with_source_event_id(client: TestClient, db_session: Session):
    """Scenario 4A: Resubmitting measurement with source_event_id returns idempotent response."""
    proj_resp = client.get("/api/v1/projects")
    project_id = UUID(proj_resp.json()[0]["id"])
    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    service = svc_resp.json()[0]
    service_id = service["identifier"]

    t0 = datetime(2026, 11, 5, 14, 0, 0, tzinfo=timezone.utc)
    for i in range(4):
        client.post(
            "/api/v1/anomalies/evaluate",
            json={
                "project_id": str(project_id),
                "service_identifier": service_id,
                "metric_name": "latency",
                "observed_value": 50.0,
                "timestamp": (t0 + timedelta(seconds=i * 5)).isoformat(),
            },
        )

    # Submit anomaly with source_event_id
    payload = {
        "project_id": str(project_id),
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": 200.0,
        "timestamp": (t0 + timedelta(seconds=60)).isoformat(),
        "source_event_id": "evt-idempotency-test-001",
    }
    res1 = client.post("/api/v1/anomalies/evaluate", json=payload)
    assert res1.status_code == 200
    assert res1.json()["is_anomaly"] is True

    # Resubmit identical request with same source_event_id
    res2 = client.post("/api/v1/anomalies/evaluate", json=payload)
    assert res2.status_code == 200
    assert res2.json()["is_anomaly"] is True
    assert res2.json()["observed_value"] == 200.0

    # Ensure only 1 event row is stored
    db_session.expire_all()
    events = (
        db_session.query(AnomalyEvent)
        .filter(AnomalyEvent.source_event_id == "evt-idempotency-test-001")
        .all()
    )
    assert len(events) == 1


def test_duplicate_timestamp_rejected_as_conflict(client: TestClient):
    """Scenario 4B: Resubmitting with an existing or older timestamp is rejected with 409 Conflict."""
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]
    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    service_id = svc_resp.json()[0]["identifier"]

    event_time = datetime(2026, 11, 5, 15, 0, 0, tzinfo=timezone.utc).isoformat()
    p1 = {
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "request_rate",
        "observed_value": 500.0,
        "timestamp": event_time,
    }
    r1 = client.post("/api/v1/anomalies/evaluate", json=p1)
    assert r1.status_code == 200

    # Same timestamp resubmitted
    r2 = client.post("/api/v1/anomalies/evaluate", json=p1)
    assert r2.status_code == 409
    assert "strictly newer" in r2.json()["detail"].lower()


def test_transaction_failure_rollback_and_memory_consistency(client: TestClient, db_session: Session):
    """Scenario 5: Simulated DB failure rolls back transaction and evicts in-memory detector."""
    proj_resp = client.get("/api/v1/projects")
    project_id = UUID(proj_resp.json()[0]["id"])
    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    service = svc_resp.json()[0]
    service_id = service["identifier"]

    # 1. Warm up baseline cleanly
    t0 = datetime(2026, 11, 5, 16, 0, 0, tzinfo=timezone.utc)
    for i in range(4):
        client.post(
            "/api/v1/anomalies/evaluate",
            json={
                "project_id": str(project_id),
                "service_identifier": service_id,
                "metric_name": "latency",
                "observed_value": 100.0,
                "timestamp": (t0 + timedelta(seconds=i * 5)).isoformat(),
            },
        )

    db_baseline_before = (
        db_session.query(AnomalyBaseline)
        .filter(AnomalyBaseline.project_id == project_id, AnomalyBaseline.metric_name == "latency")
        .first()
    )
    v_before = db_baseline_before.version

    # 2. Simulate database failure during commit
    svc = AnomalyService(db_session)
    req = AnomalyEvaluationRequest(
        project_id=project_id,
        service_identifier=service_id,
        metric_name="latency",
        observed_value=105.0,
        timestamp=t0 + timedelta(seconds=50),
    )
    with patch.object(db_session, "commit", side_effect=RuntimeError("Simulated DB connection failure")):
        with pytest.raises(RuntimeError):
            svc.evaluate_measurement(req)

    # 3. Verify in-memory detector was evicted so memory is not ahead of DB
    detector_in_memory = get_anomaly_registry().get(project_id, service_id, "latency")
    assert detector_in_memory is None  # Cleanly evicted on rollback!

    # 4. Verify DB was rolled back (version unchanged)
    db_session.expire_all()
    baseline_after_fail = (
        db_session.query(AnomalyBaseline)
        .filter(AnomalyBaseline.project_id == project_id, AnomalyBaseline.metric_name == "latency")
        .first()
    )
    assert baseline_after_fail.version == v_before


def test_concurrent_measurements_thread_safety(db_session: Session):
    """Scenario 6: Concurrent measurements for different metrics/services operate safely without lost updates."""
    # Create isolated test project and service
    proj_svc = db_session.query(Service).first()
    project_id = proj_svc.project_id
    service_id = proj_svc.identifier

    errors = []
    base_time = datetime(2026, 11, 5, 18, 0, 0, tzinfo=timezone.utc)
    db_lock = threading.Lock()

    def worker(metric_idx: int):
        metric = f"metric_concurrency_{metric_idx}"
        try:
            for step in range(5):
                req = AnomalyEvaluationRequest(
                    project_id=project_id,
                    service_identifier=service_id,
                    metric_name=metric,
                    observed_value=100.0 + float(step),
                    timestamp=base_time + timedelta(seconds=step * 10),
                )
                with db_lock:
                    session = TestingSessionLocal()
                    try:
                        svc = AnomalyService(session)
                        resp = svc.evaluate_measurement(req)
                        assert resp is not None
                    finally:
                        session.close()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0

    # Verify all 4 metrics were persisted in database
    baselines = (
        db_session.query(AnomalyBaseline)
        .filter(
            AnomalyBaseline.project_id == project_id,
            AnomalyBaseline.metric_name.like("metric_concurrency_%"),
        )
        .all()
    )
    assert len(baselines) == 4
    for b in baselines:
        assert b.sample_count >= 3
        assert b.version == 5
