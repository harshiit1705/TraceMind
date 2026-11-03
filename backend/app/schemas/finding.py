from datetime import datetime
from typing import List
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.common import FindingStatus


class FindingResponse(BaseModel):
    id: UUID
    investigation_id: UUID
    rank: int
    title: str
    probable_root_cause: str
    explanation: str
    status: FindingStatus
    confidence_score: float = Field(ge=0.0, le=100.0)
    affected_services: List[str]
    supporting_evidence_ids: List[str]
    is_demo: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

