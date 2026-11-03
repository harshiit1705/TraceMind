from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    name: str = Field(..., max_length=128, description="Human-readable project name")
    slug: str = Field(..., max_length=64, description="URL-safe unique project slug")
    environment: str = Field(default="production", max_length=32)
    description: Optional[str] = Field(default=None, max_length=512)
    is_demo: bool = Field(default=True, description="Indicates simulated demonstration project")


class ProjectCreate(ProjectBase):
    organization_id: UUID


class ProjectResponse(ProjectBase):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

