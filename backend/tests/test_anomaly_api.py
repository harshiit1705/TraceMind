import threading
import uuid
from fastapi.testclient import TestClient
from app.services.anomaly.registry import get_anomaly_registry


def test_evaluate_warmup_to_normal_to_anomaly(client: TestClient):
    # Fetch default seeded project and service
    proj_resp = client.get("/api/v1/projects")
    assert proj_resp.status_code == 200
    project = proj_resp.json()[0]
    project_id = project["id"]

    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    assert svc_resp.status_code == 200
    service = svc_resp.json()[0]
    service_id = service["identifier"]

    # Samples 1-3: Warmup accumulation (min_samples=3 by default)
    for i in range(3):
        payload = {
            "project_id": project_id,
            "service_identifier": service_id,
            "metric_name": "latency",
            "observed_value": 100.0,
        }
        res = client.post("/api/v1/anomalies/evaluate", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["detection_status"] == "WARMING_UP"
        assert data["is_anomaly"] is False
        assert data["expected_baseline"] is None
        assert data["sample_count"] == i
        assert "warming up" in data["explanation"].lower()

    # Sample 4: Detector is now ready. Normal measurement
    payload = {
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": 102.0,
    }
    res4 = client.post("/api/v1/anomalies/evaluate", json=payload)
    assert res4.status_code == 200
    data4 = res4.json()
    assert data4["detection_status"] == "NORMAL"
    assert data4["is_anomaly"] is False
    assert data4["expected_baseline"] == 100.0
    assert data4["sample_count"] == 3

    # Sample 5: Spike (+100% > 30% threshold)
    payload_spike = {
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": 200.0,
    }
    res5 = client.post("/api/v1/anomalies/evaluate", json=payload_spike)
    assert res5.status_code == 200
    data5 = res5.json()
    assert data5["detection_status"] == "ANOMALY"
    assert data5["is_anomaly"] is True
    assert data5["severity"] in ("HIGH", "CRITICAL")
    assert data5["deviation_pct"] > 90.0

    # Sample 6: Anti-contamination verification
    # Normal reading after spike: baseline must NOT include the 200.0 spike
    payload_normal = {
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": 104.0,
    }
    res6 = client.post("/api/v1/anomalies/evaluate", json=payload_normal)
    assert res6.status_code == 200
    data6 = res6.json()
    assert data6["detection_status"] == "NORMAL"
    assert data6["is_anomaly"] is False
    # Expected baseline should be around 100.5 (from [100, 100, 100, 102]), not pulled up by 200
    assert data6["expected_baseline"] < 105.0


def test_service_baseline_isolation(client: TestClient):
    proj_resp = client.get("/api/v1/projects")
    project = proj_resp.json()[0]
    project_id = project["id"]

    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    services = svc_resp.json()
    svc_a = services[0]["identifier"]  # e.g. api-gateway
    svc_b = services[1]["identifier"]  # e.g. payment-service

    # Warmup Service A around 100.0 ms
    for _ in range(3):
        client.post("/api/v1/anomalies/evaluate", json={
            "project_id": project_id,
            "service_identifier": svc_a,
            "metric_name": "latency",
            "observed_value": 100.0,
        })

    # Warmup Service B around 500.0 ms
    for _ in range(3):
        client.post("/api/v1/anomalies/evaluate", json={
            "project_id": project_id,
            "service_identifier": svc_b,
            "metric_name": "latency",
            "observed_value": 500.0,
        })

    # Test Service A with 160.0 ms (+60% > 30% threshold) -> ANOMALY
    res_a = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": project_id,
        "service_identifier": svc_a,
        "metric_name": "latency",
        "observed_value": 160.0,
    })
    assert res_a.json()["is_anomaly"] is True
    assert res_a.json()["expected_baseline"] == 100.0

    # Test Service B with 510.0 ms (+2% < 30% threshold) -> NORMAL
    res_b = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": project_id,
        "service_identifier": svc_b,
        "metric_name": "latency",
        "observed_value": 510.0,
    })
    assert res_b.json()["is_anomaly"] is False
    assert res_b.json()["expected_baseline"] == 500.0


def test_metric_baseline_isolation(client: TestClient):
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]
    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    service_id = svc_resp.json()[0]["identifier"]

    # Warmup latency at 50ms
    for _ in range(3):
        client.post("/api/v1/anomalies/evaluate", json={
            "project_id": project_id,
            "service_identifier": service_id,
            "metric_name": "latency",
            "observed_value": 50.0,
        })

    # Warmup request_rate at 2000 rps
    for _ in range(3):
        client.post("/api/v1/anomalies/evaluate", json={
            "project_id": project_id,
            "service_identifier": service_id,
            "metric_name": "request_rate",
            "observed_value": 2000.0,
        })

    # Check latency baseline
    res_lat = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": 52.0,
    })
    assert res_lat.json()["expected_baseline"] == 50.0

    # Check request_rate baseline
    res_rate = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "request_rate",
        "observed_value": 2010.0,
    })
    assert res_rate.json()["expected_baseline"] == 2000.0


def test_unknown_service_returns_404_without_polluting_registry(client: TestClient):
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]
    registry = get_anomaly_registry()

    initial_count = registry.count()

    res = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": project_id,
        "service_identifier": "unknown-nonexistent-service",
        "metric_name": "latency",
        "observed_value": 120.0,
    })
    assert res.status_code == 404
    assert "was not found" in res.json()["detail"]

    # Verify no baseline was silently created
    assert registry.count() == initial_count
    assert registry.get(uuid.UUID(project_id), "unknown-nonexistent-service", "latency") is None


def test_project_service_mismatch_returns_404_without_polluting_registry(client: TestClient):
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]
    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    valid_service_slug = svc_resp.json()[0]["slug"]

    registry = get_anomaly_registry()
    initial_count = registry.count()

    fake_project_id = str(uuid.uuid4())

    res = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": fake_project_id,
        "service_identifier": valid_service_slug,
        "metric_name": "latency",
        "observed_value": 120.0,
    })
    assert res.status_code == 404
    assert "was not found" in res.json()["detail"]

    # Verify no baseline was created under the mismatched project
    assert registry.count() == initial_count


def test_payload_validation_rejects_invalid_inputs(client: TestClient):
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]
    svc_resp = client.get(f"/api/v1/services?project_id={project_id}")
    service_id = svc_resp.json()[0]["identifier"]

    # 1. Reject boolean observed_value (True)
    res_bool = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": True,
    })
    assert res_bool.status_code == 422

    # 2. Reject empty metric_name
    res_empty_metric = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "   ",
        "observed_value": 100.0,
    })
    assert res_empty_metric.status_code == 422

    # 3. Reject negative latency
    res_neg_lat = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": -45.0,
    })
    assert res_neg_lat.status_code == 422

    # 4. Reject invalid UUID format
    res_bad_uuid = client.post("/api/v1/anomalies/evaluate", json={
        "project_id": "not-a-valid-uuid",
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": 100.0,
    })
    assert res_bad_uuid.status_code == 422


def test_thread_safe_registry_concurrency():
    registry = get_anomaly_registry()
    project_id = uuid.uuid4()
    errors = []

    def worker(worker_id: int):
        try:
            for i in range(20):
                svc = f"svc-{worker_id % 3}"
                metric = f"metric-{i % 2}"
                detector = registry.get_or_create(project_id, svc, metric)
                detector.update_baseline(metric, 10.0 + float(i))
                _ = detector.evaluate(metric, 15.0)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    # 3 services * 2 metrics = 6 detectors
    assert registry.count() == 6



def test_timestamp_api_rejects_naive_and_duplicate_event_times(client: TestClient):
    from datetime import datetime, timezone

    project_id = client.get("/api/v1/projects").json()[0]["id"]
    service_id = client.get(f"/api/v1/services?project_id={project_id}").json()[0]["identifier"]
    base_payload = {
        "project_id": project_id,
        "service_identifier": service_id,
        "metric_name": "latency",
        "observed_value": 100.0,
    }

    naive = client.post(
        "/api/v1/anomalies/evaluate",
        json={**base_payload, "timestamp": "2026-11-05T10:00:00"},
    )
    assert naive.status_code == 422

    event_time = "2026-11-05T10:00:00+05:30"
    first = client.post(
        "/api/v1/anomalies/evaluate",
        json={**base_payload, "timestamp": event_time},
    )
    assert first.status_code == 200
    assert first.json()["timestamp"] == "2026-11-05T04:30:00Z"

    duplicate = client.post(
        "/api/v1/anomalies/evaluate",
        json={**base_payload, "timestamp": event_time},
    )
    assert duplicate.status_code == 409

    older = client.post(
        "/api/v1/anomalies/evaluate",
        json={**base_payload, "timestamp": "2026-11-05T09:59:59+05:30"},
    )
    assert older.status_code == 409
