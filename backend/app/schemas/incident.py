from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.common import IncidentSeverity, IncidentStatus


class IncidentEventResponse(BaseModel):
    id: UUID
    incident_id: UUID
    timestamp: datetime
    title: str
    event_type: str
    source: str
    description: str
    payload: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class IncidentBase(BaseModel):
    incident_number: str = Field(..., max_length=32, description="Unique incident identifier, e.g. INC-8492")
    correlation_group_id: Optional[UUID] = Field(default=None, description="Associated correlation group identifier")
    title: str = Field(..., max_length=256)
    severity: IncidentSeverity
    status: IncidentStatus
    started_at: datetime
    mitigated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    commander_name: str = Field(default="Alex Chen", max_length=128)
    commander_role: str = Field(default="Staff SRE", max_length=128)
    root_cause_summary: Optional[str] = None
    affected_services: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    is_demo: bool = Field(default=True, description="Indicates simulated demo incident scenario")


class IncidentResponse(IncidentBase):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentDetailResponse(IncidentResponse):
    events: List[IncidentEventResponse] = Field(default_factory=list)


class IncidentStatusUpdateRequest(BaseModel):
    status: IncidentStatus = Field(..., description="Target incident status")
    commander_name: Optional[str] = Field(default=None, max_length=128, description="Updated commander name if transferring incident lead")
    commander_role: Optional[str] = Field(default=None, max_length=128, description="Updated commander role")
    comment: Optional[str] = Field(default=None, description="Optional transition note or rationale recorded in timeline")

    model_config = ConfigDict(extra="forbid")


class IncidentCreateRequest(BaseModel):
    title: str = Field(..., max_length=256, description="Brief summary title of the incident")
    severity: IncidentSeverity = Field(..., description="Initial incident severity level")
    correlation_group_id: Optional[UUID] = Field(default=None, description="Optional correlation group ID linking distributed anomaly cluster")
    affected_services: List[str] = Field(default_factory=list, description="List of services impacted by this incident")
    summary: Optional[str] = Field(default=None, description="Detailed initial problem description or context")
    commander_name: Optional[str] = Field(default="Alex Chen", max_length=128, description="Assigned incident commander")
    commander_role: Optional[str] = Field(default="Staff SRE", max_length=128, description="Role of the incident commander")

    model_config = ConfigDict(extra="forbid")


class TimelineResponse(BaseModel):
    incident_id: UUID
    incident_number: str
    events: List[IncidentEventResponse]

