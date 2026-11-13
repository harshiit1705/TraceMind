"""Pydantic schemas for Phase 5: Telemetry-Based Recovery Verification."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class RecoveryOutcome(str, Enum):
    """Deterministic telemetry recovery outcome."""
    RECOVERED = "RECOVERED"
    NOT_RECOVERED = "NOT_RECOVERED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    INCONCLUSIVE = "INCONCLUSIVE"


class VerificationStatus(str, Enum):
    """Lifecycle status of the verification evaluation process."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CheckStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class TelemetryCheckResult(BaseModel):
    check_name: str = Field(..., description="Unique check identifier, e.g. latency_p95_baseline")
    status: CheckStatus = Field(..., description="PASSED, FAILED, or INCONCLUSIVE")
    metric_name: Optional[str] = None
    observed_value: Optional[Any] = None
    baseline_expected: Optional[Any] = None
    details: str = Field(..., description="Explainable description of the check result")


class RecoveryVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_window_seconds: int = Field(
        default=60,
        ge=5,
        le=600,
        description="Duration of the post-remediation evaluation window in seconds"
    )
    min_sample_count: int = Field(
        default=3,
        ge=1,
        le=100,
        description="Minimum telemetry samples required to avoid INCONCLUSIVE zero-traffic conclusion"
    )


class RecoveryVerificationResponse(BaseModel):
    id: UUID
    incident_id: UUID
    remediation_id: UUID
    project_id: UUID
    execution_attempt_id: Optional[str] = None
    target_service: str
    status: VerificationStatus
    recovery_outcome: Optional[RecoveryOutcome] = None
    verification_window_start: datetime
    verification_window_end: datetime
    sample_count: int = 0
    checks_summary: List[TelemetryCheckResult] = Field(default_factory=list)
    evidence_snapshot: Dict[str, Any] = Field(default_factory=dict)
    explanation: Optional[str] = None
    error_message: Optional[str] = None
    verified_by: Optional[str] = None
    suggested_incident_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
