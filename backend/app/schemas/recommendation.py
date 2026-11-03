from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.common import RiskLevel


class RecommendationResponse(BaseModel):
    id: UUID
    investigation_id: UUID
    finding_id: Optional[UUID] = None
    title: str
    action_type: str
    description: str
    command_snippet: Optional[str] = None
    risk_level: RiskLevel
    is_dry_run_safe: bool = True
    requires_human_approval: bool = True
    is_demo: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

