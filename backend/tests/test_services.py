from fastapi.testclient import TestClient


def test_list_all_services(client: TestClient):
    response = client.get("/api/v1/services")
    assert response.status_code == 200
    services = response.json()
    assert len(services) == 10


def test_filter_services_by_tier(client: TestClient):
    response = client.get("/api/v1/services?tier=0")
    assert response.status_code == 200
    services = response.json()
    assert len(services) > 0
    for s in services:
        assert s["tier"] == 0


def test_filter_services_by_status(client: TestClient):
    response = client.get("/api/v1/services?status=unhealthy")
    assert response.status_code == 200
    services = response.json()
    assert len(services) == 1
    assert services[0]["slug"] == "postgres"
    assert services[0]["status"] == "unhealthy"


def test_service_metric_consistency(client: TestClient):
    response = client.get("/api/v1/services")
    services = {s["slug"]: s for s in response.json()}

    # Check Aurora DB metrics match incident specifications
    db_svc = services["postgres"]
    assert db_svc["error_rate_percent"] == 14.20
    assert db_svc["p95_latency_ms"] == 2400.0

    # Check Payment Service metrics
    pay_svc = services["payment-service"]
    assert pay_svc["p95_latency_ms"] == 1420.0
    assert pay_svc["error_rate_percent"] == 8.85
