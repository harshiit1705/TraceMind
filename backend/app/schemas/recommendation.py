from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.common import RiskLevel


class RemediationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    CANCELLED = "CANCELLED"


class RemediationExecutionMode(str, Enum):
    REAL = "REAL"
    SIMULATED = "SIMULATED"


class AllowlistedAction(str, Enum):
    RESET_SERVICE_FAULTS = "RESET_SERVICE_FAULTS"
    RESTART_SERVICE = "RESTART_SERVICE"
    SCALE_REPLICAS = "SCALE_REPLICAS"
    ROLLBACK_DEPLOYMENT = "ROLLBACK_DEPLOYMENT"
    FLUSH_CONNECTION_POOL = "FLUSH_CONNECTION_POOL"
    DRAIN_TRAFFIC = "DRAIN_TRAFFIC"


class RemediationApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_notes: Optional[str] = Field(None, max_length=1000, description="Optional justification or context for approval")
    approver_name: Optional[str] = Field(None, max_length=128, description="Optional client label; validated/overridden by authenticated principal")


class RemediationRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejection_reason: str = Field(..., min_length=3, max_length=1000, description="Mandatory justification for rejection")
    rejector_name: Optional[str] = Field(None, max_length=128, description="Optional client label; validated/overridden by authenticated principal")


class RemediationExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_mode: Optional[RemediationExecutionMode] = Field(
        None,
        description="Explicit execution mode: REAL against running microservices or safe SIMULATED"
    )
    idempotency_key: Optional[str] = Field(
        None,
        min_length=8,
        max_length=64,
        description="Unique client idempotency token to prevent double-execution"
    )
    executor_name: Optional[str] = Field(None, max_length=128, description="Optional client label; validated/overridden by authenticated principal")


class RemediationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cancellation_reason: Optional[str] = Field(None, max_length=1000, description="Optional cancellation notes")
    cancelled_by: Optional[str] = Field(None, max_length=128, description="Optional client label; validated/overridden by authenticated principal")


class RemediationReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_notes: Optional[str] = Field(None, max_length=1000, description="Audit notes explaining the reconciliation decision")
    force_outcome: Optional[RemediationStatus] = Field(
        default=RemediationStatus.OUTCOME_UNKNOWN,
        description="Target status for reconciliation: OUTCOME_UNKNOWN or FAILED"
    )


class RemediationProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=5, max_length=256)
    description: str = Field(..., min_length=10)
    target_service: str = Field(..., min_length=1, max_length=128)
    action_name: AllowlistedAction = Field(...)
    action_type: str = Field(default="immediate")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    action_parameters: Dict[str, Any] = Field(default_factory=dict)
    preconditions: List[str] = Field(default_factory=list)
    rollback_procedure: Optional[str] = None
    expected_result: Optional[str] = None
    verification_steps: List[str] = Field(default_factory=list)
    proposer_name: str = Field(default="human_operator", max_length=128)


class RecommendationResponse(BaseModel):
    id: UUID
    investigation_id: UUID
    finding_id: Optional[UUID] = None
    title: str
    action_type: str
    action_name: Optional[str] = None
    target_service: Optional[str] = None
    description: str
    command_snippet: Optional[str] = None
    risk_level: RiskLevel
    status: RemediationStatus = RemediationStatus.PROPOSED
    is_dry_run_safe: bool = True
    requires_human_approval: bool = True
    is_demo: bool = True
    action_parameters: Optional[Dict[str, Any]] = None
    preconditions: Optional[List[str]] = None
    rollback_procedure: Optional[str] = None
    expected_result: Optional[str] = None
    verification_steps: Optional[List[str]] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_notes: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    executed_by: Optional[str] = None
    executed_at: Optional[datetime] = None
    execution_started_at: Optional[datetime] = None
    execution_lease_expires_at: Optional[datetime] = None
    execution_attempt_id: Optional[str] = None
    execution_mode: Optional[str] = None
    execution_idempotency_key: Optional[str] = None
    execution_result_json: Optional[Dict[str, Any]] = None
    execution_error: Optional[str] = None
    incident_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RemediationDetailResponse(RecommendationResponse):
    incident_id: Optional[UUID] = None
    incident_number: Optional[str] = None
    project_id: Optional[UUID] = None
