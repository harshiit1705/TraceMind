import uuid
from fastapi.testclient import TestClient


def test_list_projects(client: TestClient):
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    projects = response.json()
    assert isinstance(projects, list)
    assert len(projects) >= 1
    default_proj = next((p for p in projects if p["slug"] == "core-ecommerce"), None)
    assert default_proj is not None
    assert default_proj["name"] == "Core E-Commerce & Payments"
    assert default_proj["is_demo"] is True


def test_list_project_services(client: TestClient):
    # First get the project
    p_res = client.get("/api/v1/projects")
    project_id = p_res.json()[0]["id"]

    # Now fetch services for this project
    response = client.get(f"/api/v1/projects/{project_id}/services")
    assert response.status_code == 200
    services = response.json()
    assert len(services) == 10

    slugs = [s["slug"] for s in services]
    assert "api-gateway" in slugs
    assert "order-service" in slugs
    assert "payment-service" in slugs
    assert "postgres" in slugs


def test_list_services_nonexistent_project(client: TestClient):
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/projects/{fake_id}/services")
    assert response.status_code == 404
