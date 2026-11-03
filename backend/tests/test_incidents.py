import uuid
from fastapi.testclient import TestClient


def test_list_incidents(client: TestClient):
    response = client.get("/api/v1/incidents")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    assert data["page_size"] == 20
    assert data["page"] == 1


def test_filter_incidents(client: TestClient):
    response = client.get("/api/v1/incidents?severity=CRITICAL&status=INVESTIGATING")
    assert response.status_code == 200
    data = response.json()
    for item in data["items"]:
        assert item["severity"] == "CRITICAL"
        assert item["status"] == "INVESTIGATING"


def test_get_incident_by_identifier(client: TestClient):
    response = client.get("/api/v1/incidents/INC-8492")
    assert response.status_code == 200
    data = response.json()
    assert data["incident_number"] == "INC-8492"
    assert "pool exhaustion" in data["title"].lower()
    assert data["severity"] == "CRITICAL"
    assert data["status"] == "INVESTIGATING"
    assert len(data["affected_services"]) >= 3
    assert len(data["events"]) >= 5


def test_get_incident_by_uuid(client: TestClient):
    # Lookup INC-8492 first to get its UUID
    res = client.get("/api/v1/incidents/INC-8492")
    inc_uuid = res.json()["id"]

    # Now retrieve using UUID
    response = client.get(f"/api/v1/incidents/{inc_uuid}")
    assert response.status_code == 200
    assert response.json()["id"] == inc_uuid
    assert response.json()["incident_number"] == "INC-8492"


def test_get_nonexistent_incident(client: TestClient):
    response = client.get("/api/v1/incidents/INC-999999")
    assert response.status_code == 404
    assert "not found" in response.json()["error"].lower()


def test_get_incident_timeline(client: TestClient):
    response = client.get("/api/v1/incidents/INC-8492/timeline")
    assert response.status_code == 200
    data = response.json()
    assert data["incident_number"] == "INC-8492"
    assert len(data["events"]) >= 5

    # Check chronological ordering
    timestamps = [e["timestamp"] for e in data["events"]]
    assert timestamps == sorted(timestamps)
