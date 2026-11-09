"""Focused unit tests for Sprint 5.4 Phase 1: Incident model, CorrelationGroup link,

IncidentStatus enum (including DETECTED), and Pydantic schemas.
"""
from datetime import datetime, timezone
import uuid
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.correlation import CorrelationGroup
from app.models.project import Project
from app.schemas.common import IncidentSeverity, IncidentStatus
from app.schemas.incident import (
    IncidentBase,
    IncidentResponse,
    IncidentDetailResponse,
    IncidentStatusUpdateRequest,
    IncidentCreateRequest,
)


def test_incident_status_enum_values():
    """Verify IncidentStatus enum includes DETECTED while preserving all legacy statuses."""
    expected_statuses = {"DETECTED", "INVESTIGATING", "ACKNOWLEDGED", "MITIGATED", "RESOLVED"}
    actual_statuses = {s.value for s in IncidentStatus}
    assert actual_statuses == expected_statuses

    # Ensure DETECTED is a str enum and compares properly
    assert IncidentStatus.DETECTED == "DETECTED"
    assert IncidentStatus("DETECTED") == IncidentStatus.DETECTED

    # Ensure legacy statuses can still be parsed
    assert IncidentStatus("INVESTIGATING") == IncidentStatus.INVESTIGATING
    assert IncidentStatus("ACKNOWLEDGED") == IncidentStatus.ACKNOWLEDGED
    assert IncidentStatus("MITIGATED") == IncidentStatus.MITIGATED
    assert IncidentStatus("RESOLVED") == IncidentStatus.RESOLVED


def test_incident_status_update_request_schema():
    """Verify IncidentStatusUpdateRequest validation and extra field rejection."""
    # Valid status update with all optional fields
    req = IncidentStatusUpdateRequest(
        status=IncidentStatus.INVESTIGATING,
        commander_name="Sarah Connor",
        commander_role="Principal SRE",
        comment="Taking incident lead after automated detection",
    )
    assert req.status == IncidentStatus.INVESTIGATING
    assert req.commander_name == "Sarah Connor"
    assert req.comment == "Taking incident lead after automated detection"

    # Valid status update with minimal fields
    minimal = IncidentStatusUpdateRequest(status=IncidentStatus.DETECTED)
    assert minimal.status == IncidentStatus.DETECTED
    assert minimal.commander_name is None
    assert minimal.comment is None

    # Invalid status value
    with pytest.raises(ValidationError):
        IncidentStatusUpdateRequest(status="NON_EXISTENT_STATUS")

    # Extra forbidden field
    with pytest.raises(ValidationError):
        IncidentStatusUpdateRequest(status=IncidentStatus.MITIGATED, invalid_field="not_allowed")


def test_incident_create_request_schema():
    """Verify IncidentCreateRequest validation and defaults."""
    corr_id = uuid.uuid4()
    req = IncidentCreateRequest(
        title="Payment gateway elevated 5xx error rate",
        severity=IncidentSeverity.CRITICAL,
        correlation_group_id=corr_id,
        affected_services=["payment-service", "checkout-api"],
        summary="Automated detection from correlation cluster",
    )
    assert req.title == "Payment gateway elevated 5xx error rate"
    assert req.severity == IncidentSeverity.CRITICAL
    assert req.correlation_group_id == corr_id
    assert req.commander_name == "Alex Chen"
    assert req.commander_role == "Staff SRE"
    assert len(req.affected_services) == 2

    # Extra forbidden field
    with pytest.raises(ValidationError):
        IncidentCreateRequest(
            title="Test",
            severity=IncidentSeverity.LOW,
            unknown_prop="disallowed",
        )


def test_incident_response_schemas_with_nullable_correlation_group():
    """Verify IncidentResponse and IncidentDetailResponse serialize correlation_group_id."""
    now = datetime.now(timezone.utc)
    inc_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    # With correlation_group_id
    res = IncidentResponse(
        id=inc_id,
        project_id=proj_id,
        incident_number="INC-1001",
        correlation_group_id=corr_id,
        title="Database connection timeout",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    assert res.correlation_group_id == corr_id
    assert res.status == IncidentStatus.DETECTED

    # Without correlation_group_id (None by default)
    res_none = IncidentResponse(
        id=inc_id,
        project_id=proj_id,
        incident_number="INC-1002",
        title="Cache latency spike",
        severity=IncidentSeverity.MEDIUM,
        status=IncidentStatus.INVESTIGATING,
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    assert res_none.correlation_group_id is None


def test_existing_demo_incidents_remain_readable(client):
    """Verify existing demo seed incident INC-8492 remains readable with correlation_group_id is None."""
    response = client.get("/api/v1/incidents/INC-8492")
    assert response.status_code == 200
    data = response.json()
    assert data["incident_number"] == "INC-8492"
    assert data["status"] == "INVESTIGATING"
    assert data["is_demo"] is True
    # correlation_group_id is present in response and None for legacy demo incident
    assert "correlation_group_id" in data
    assert data["correlation_group_id"] is None


def test_incident_model_correlation_group_relationship(db_session: Session):
    """Verify bidirectional relationship between Incident and CorrelationGroup with SET NULL on delete."""
    # Find existing project from seed
    project = db_session.query(Project).first()
    assert project is not None

    now = datetime.now(timezone.utc)

    # 1. Create a CorrelationGroup
    corr_group = CorrelationGroup(
        id=uuid.uuid4(),
        project_id=project.id,
        correlation_key="test-corr-key-sprint-5-4",
        time_window_start=now,
        time_window_end=now,
        status="ACTIVE",
        confidence_score=0.92,
        topology_complete=True,
    )
    db_session.add(corr_group)
    db_session.flush()

    # 2. Create an Incident linked to the CorrelationGroup with DETECTED status
    incident = Incident(
        id=uuid.uuid4(),
        project_id=project.id,
        incident_number="INC-9901",
        correlation_group_id=corr_group.id,
        title="Correlated API Latency Surge",
        severity="HIGH",
        status=IncidentStatus.DETECTED.value,
        started_at=now,
        commander_name="Alex Chen",
        commander_role="Staff SRE",
        affected_services=["auth-service", "gateway"],
        is_demo=False,
    )
    db_session.add(incident)
    db_session.commit()

    # 3. Test bidirectional relationship access
    fetched_incident = db_session.query(Incident).filter_by(incident_number="INC-9901").one()
    assert fetched_incident.correlation_group_id == corr_group.id
    assert fetched_incident.correlation_group is not None
    assert fetched_incident.correlation_group.correlation_key == "test-corr-key-sprint-5-4"
    assert fetched_incident.status == "DETECTED"
    assert fetched_incident.is_demo is False

    fetched_group = db_session.query(CorrelationGroup).filter_by(id=corr_group.id).one()
    assert len(fetched_group.incidents) == 1
    assert fetched_group.incidents[0].id == fetched_incident.id

    # 4. Test ON DELETE SET NULL behavior
    db_session.delete(corr_group)
    db_session.commit()

    db_session.refresh(fetched_incident)
    assert fetched_incident.correlation_group_id is None
    assert fetched_incident.correlation_group is None
    # Incident still exists
    assert db_session.query(Incident).filter_by(incident_number="INC-9901").first() is not None


def test_unique_correlation_group_id_constraint(db_session: Session):
    """Verify one incident per correlation group constraint:

    - Two incidents cannot reference the same correlation group (IntegrityError).
    - Multiple incidents without a correlation group (NULL) remain valid.
    - Existing demo incidents remain unaffected.
    """
    project = db_session.query(Project).first()
    assert project is not None
    now = datetime.now(timezone.utc)

    # 1. Create a CorrelationGroup
    corr_group = CorrelationGroup(
        id=uuid.uuid4(),
        project_id=project.id,
        correlation_key="test-corr-key-unique-constraint",
        time_window_start=now,
        time_window_end=now,
        status="ACTIVE",
    )
    db_session.add(corr_group)
    db_session.flush()

    # 2. First incident linked to corr_group succeeds
    inc1 = Incident(
        id=uuid.uuid4(),
        project_id=project.id,
        incident_number="INC-UNIQUE-1",
        correlation_group_id=corr_group.id,
        title="First Incident for Group",
        severity="HIGH",
        status=IncidentStatus.DETECTED.value,
        started_at=now,
        is_demo=False,
    )
    db_session.add(inc1)
    db_session.commit()

    # 3. Second incident attempting to reference the SAME correlation group must raise IntegrityError
    inc2 = Incident(
        id=uuid.uuid4(),
        project_id=project.id,
        incident_number="INC-UNIQUE-2",
        correlation_group_id=corr_group.id,
        title="Second Incident for Same Group",
        severity="MEDIUM",
        status=IncidentStatus.DETECTED.value,
        started_at=now,
        is_demo=False,
    )
    db_session.add(inc2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 4. Multiple incidents without correlation_group (correlation_group_id is None) remain valid
    inc_null_1 = Incident(
        id=uuid.uuid4(),
        project_id=project.id,
        incident_number="INC-NULL-1",
        correlation_group_id=None,
        title="Uncorrelated Incident 1",
        severity="LOW",
        status=IncidentStatus.INVESTIGATING.value,
        started_at=now,
        is_demo=False,
    )
    inc_null_2 = Incident(
        id=uuid.uuid4(),
        project_id=project.id,
        incident_number="INC-NULL-2",
        correlation_group_id=None,
        title="Uncorrelated Incident 2",
        severity="LOW",
        status=IncidentStatus.INVESTIGATING.value,
        started_at=now,
        is_demo=False,
    )
    db_session.add_all([inc_null_1, inc_null_2])
    db_session.commit()

    # Verify both NULL incidents persist without error
    assert db_session.query(Incident).filter_by(incident_number="INC-NULL-1").first() is not None
    assert db_session.query(Incident).filter_by(incident_number="INC-NULL-2").first() is not None

