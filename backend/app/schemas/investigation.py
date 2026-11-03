from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.common import InvestigationStatus
from app.schemas.finding import FindingResponse
from app.schemas.recommendation import RecommendationResponse


class InvestigationResponse(BaseModel):
    id: UUID
    incident_id: UUID
    agent_name: str
    status: InvestigationStatus
    summary: Optional[str] = None
    correlation_scope: int
    spans_analyzed: int
    confidence_score: Optional[float] = None
    is_demo: bool = True
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvestigationDetailResponse(InvestigationResponse):
    findings: List[FindingResponse] = Field(default_factory=list)
    recommendations: List[RecommendationResponse] = Field(default_factory=list)


class InvestigationFeedbackCreate(BaseModel):
    user_id: str = Field(default="alex.chen@acme.corp", max_length=128)
    rating: int = Field(..., ge=1, le=5, description="Investigation rating from 1 to 5")
    comments: Optional[str] = None
    was_root_cause_accurate: bool = True


class InvestigationFeedbackResponse(InvestigationFeedbackCreate):
    id: UUID
    investigation_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

