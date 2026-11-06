"""Comprehensive test suite for project-scoped service dependencies and DAG topology."""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.service import Service
from app.repositories.service_dependency_repository import (
    DependencyCycleError,
    InvalidDependencyError,
    ServiceDependencyRepository,
)


def test_dependency_dag_creation_and_traversal(client: TestClient, db_session: Session):
    """Verify directed dependency creation, adjacency lists, and graph traversal."""
    # 1. Fetch seeded project
    proj_resp = client.get("/api/v1/projects")
    assert proj_resp.status_code == 200
    project_id = proj_resp.json()[0]["id"]

    # 2. Query dependency graph
    graph_resp = client.get(f"/api/v1/dependencies/graph?project_id={project_id}")
    assert graph_resp.status_code == 200
    graph = graph_resp.json()

    assert graph["project_id"] == project_id
    assert len(graph["nodes"]) >= 10
    assert len(graph["edges"]) >= 10

    # Verify forward and reverse adjacency
    adj = graph["adjacency"]
    rev_adj = graph["reverse_adjacency"]
    assert isinstance(adj, dict)
    assert isinstance(rev_adj, dict)


def test_self_dependency_is_strictly_rejected(client: TestClient):
    """A service cannot depend on itself."""
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]
    svcs = client.get(f"/api/v1/services?project_id={project_id}").json()
    svc1 = svcs[0]["id"]

    payload = {
        "source_service_id": svc1,
        "target_service_id": svc1,
        "dependency_type": "sync",
    }
    res = client.post(f"/api/v1/dependencies?project_id={project_id}", json=payload)
    assert res.status_code == 422
    assert "self-dependencies are forbidden" in res.json()["detail"].lower()


def test_direct_dependency_cycle_is_rejected(client: TestClient, db_session: Session):
    """Direct cycle: If A -> B exists, adding B -> A must be rejected as a cycle conflict (409)."""
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]
    svcs = client.get(f"/api/v1/services?project_id={project_id}").json()
    svc_map = {s["slug"]: s["id"] for s in svcs}

    order_id = svc_map["order-service"]
    payment_id = svc_map["payment-service"]

    # order-service -> payment-service already seeded
    # Attempting payment-service -> order-service must fail with 409
    payload = {
        "source_service_id": payment_id,
        "target_service_id": order_id,
        "dependency_type": "sync",
    }
    res = client.post(f"/api/v1/dependencies?project_id={project_id}", json=payload)
    assert res.status_code == 409
    assert "cyclic dependency" in res.json()["detail"].lower()


def test_multihop_dependency_cycle_is_rejected(client: TestClient, db_session: Session):
    """Multi-hop cycle: If A -> B -> C, adding C -> A must be rejected as a cycle conflict (409)."""
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]
    svcs = client.get(f"/api/v1/services?project_id={project_id}").json()
    svc_map = {s["slug"]: s["id"] for s in svcs}

    gw_id = svc_map["api-gateway"]
    order_id = svc_map["order-service"]
    payment_id = svc_map["payment-service"]
    # api-gateway -> order-service -> payment-service
    # Attempting payment-service -> api-gateway must fail with 409
    payload = {
        "source_service_id": payment_id,
        "target_service_id": gw_id,
        "dependency_type": "sync",
    }
    res = client.post(f"/api/v1/dependencies?project_id={project_id}", json=payload)
    assert res.status_code == 409
    assert "cyclic dependency" in res.json()["detail"].lower()


def test_cross_project_dependency_is_strictly_rejected(client: TestClient, db_session: Session):
    """Services in different projects cannot form dependencies."""
    # 1. Default project
    proj_resp = client.get("/api/v1/projects")
    project_1_id = proj_resp.json()[0]["id"]
    svc_1 = client.get(f"/api/v1/services?project_id={project_1_id}").json()[0]["id"]

    # 2. Create second isolated project with a service
    org = db_session.query(Organization).first()
    proj2 = Project(
        organization_id=org.id,
        slug="isolated-project-b",
        name="Isolated Project B",
        environment="staging",
    )
    db_session.add(proj2)
    db_session.commit()
    db_session.refresh(proj2)

    svc2 = Service(
        project_id=proj2.id,
        slug="billing-worker",
        name="Billing Worker",
        identifier="svc:billing-worker",
        tier=1,
    )
    db_session.add(svc2)
    db_session.commit()
    db_session.refresh(svc2)

    # Attempt to link svc_1 (Project 1) to svc2 (Project 2) in Project 1
    payload = {
        "source_service_id": svc_1,
        "target_service_id": str(svc2.id),
        "dependency_type": "sync",
    }
    res = client.post(f"/api/v1/dependencies?project_id={project_1_id}", json=payload)
    assert res.status_code == 422
    assert "does not exist in project" in res.json()["detail"].lower()


def test_dependency_deletion(client: TestClient, db_session: Session):
    """Test deleting an established dependency edge."""
    proj_resp = client.get("/api/v1/projects")
    project_id = proj_resp.json()[0]["id"]

    deps = client.get(f"/api/v1/dependencies?project_id={project_id}").json()
    initial_count = len(deps)
    assert initial_count > 0

    target_dep = deps[0]
    del_res = client.delete(f"/api/v1/dependencies/{target_dep['id']}")
    assert del_res.status_code == 204

    # Verify count decreased
    remaining = client.get(f"/api/v1/dependencies?project_id={project_id}").json()
    assert len(remaining) == initial_count - 1

