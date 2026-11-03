from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.common import ServiceHealthStatus


class ServiceBase(BaseModel):
    name: str = Field(..., max_length=128)
    slug: str = Field(..., max_length=64)
    identifier: str = Field(..., max_length=128, description="Uniform telemetry identifier, e.g. svc:order-orchestration")
    tier: int = Field(default=1, ge=0, le=2)
    owner_team: str = Field(default="Platform Core", max_length=128)
    status: ServiceHealthStatus = Field(default=ServiceHealthStatus.HEALTHY)
    request_rate_rps: float = Field(default=0.0, ge=0.0)
    error_rate_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    p95_latency_ms: float = Field(default=0.0, ge=0.0)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class ServiceCreate(ServiceBase):
    project_id: UUID


class ServiceResponse(ServiceBase):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

