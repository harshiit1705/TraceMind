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


class TimelineResponse(BaseModel):
    incident_id: UUID
    incident_number: str
    events: List[IncidentEventResponse]

