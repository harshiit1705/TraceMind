from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.common import EvidenceType


class EvidenceResponse(BaseModel):
    id: UUID
    incident_id: UUID
    investigation_id: Optional[UUID] = None
    evidence_key: Optional[str] = Field(default=None, description="Stable human-readable evidence identifier e.g. ev-101-db-pool")
    evidence_type: EvidenceType
    service_identifier: str
    title: str
    observation: str
    confidence_weight: float
    timestamp: datetime
    payload: Dict[str, Any]
    is_demo: bool = Field(default=True, description="Indicates simulated deterministic telemetry evidence")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvidenceListResponse(BaseModel):
    incident_id: UUID
    incident_number: str
    total_count: int
    items: List[EvidenceResponse]
    is_demo_scenario: bool = True
