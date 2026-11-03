import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.services.incident_service import IncidentService


def test_get_investigation_details(client: TestClient, db_session: Session):
    svc = IncidentService(db_session)
    inv = svc.get_investigation_for_incident("INC-8492")
    assert inv is not None

    response = client.get(f"/api/v1/investigations/{inv.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(inv.id)
    assert data["status"] == "COMPLETED"
    assert data["confidence_score"] == 94.0
    assert "exhaustion" in data["summary"].lower()

    # Check findings
    assert len(data["findings"]) >= 1
    primary_finding = data["findings"][0]
    assert primary_finding["status"] == "CONFIRMED"
    assert primary_finding["confidence_score"] == 94.0
    assert len(primary_finding["supporting_evidence_ids"]) >= 1

    # Check recommendations and safety guardrails
    assert len(data["recommendations"]) >= 1
    recs = data["recommendations"]
    assert any(r["risk_level"] == "LOW" for r in recs)
    for r in recs:
        assert r["is_dry_run_safe"] is True
        assert r["requires_human_approval"] is True


def test_get_nonexistent_investigation(client: TestClient):
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/investigations/{fake_id}")
    assert response.status_code == 404
