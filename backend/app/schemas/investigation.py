from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.common import InvestigationStatus
from app.schemas.correlation import (
    BottleneckSpanEvidence,
    CorrelatedLogHighlight,
    MultiSignalTimelineEntry,
    ServiceMetricEvidence,
    SignalCoverageSummary,
)
from app.schemas.finding import FindingResponse
from app.schemas.recommendation import RecommendationResponse


# --- Sprint 5.1 Strict Evidence-Grounded Investigation Schemas ---

class RemediationActionType(str, Enum):
    CONFIGURATION = "configuration"
    SCALING = "scaling"
    RESTART = "restart"
    FAILOVER = "failover"
    ROLLBACK = "rollback"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EvidenceEventItem(BaseModel):
    """Sanitized evidence summary of a participating anomaly event."""
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    service_id: UUID
    service_name: str
    service_identifier: str
    metric_name: str
    observed_value: float
    expected_baseline: Optional[float] = None
    deviation_pct: Optional[float] = None
    severity: str
    detection_method: str
    occurred_at: datetime
    relevance_score: float
    correlation_reason: str
    has_persisted_baseline: bool = False
    baseline_mean: Optional[float] = None
    baseline_std_dev: Optional[float] = None


class EvidenceDependencyItem(BaseModel):
    """Sanitized dependency edge between participating services."""
    model_config = ConfigDict(extra="forbid")

    source_service_id: UUID
    source_service_name: str
    target_service_id: UUID
    target_service_name: str
    dependency_type: str
    description: Optional[str] = None


class EvidenceCandidateItem(BaseModel):
    """Sanitized candidate evidence for root-cause ranking."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    service_id: UUID
    service_name: str
    service_identifier: str
    rank: int
    score: float
    confidence: str
    is_probable_root_cause: bool
    temporal_precedence_score: float
    topological_score: float
    blast_radius_score: float
    severity_score: float
    reasons: Dict[str, Any] = Field(default_factory=dict)
    supporting_evidence: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    primary_suspected_operation: Optional[str] = None
    affected_downstream_services: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    neutral_signals: List[str] = Field(default_factory=list)
    missing_signals: List[str] = Field(default_factory=list)
    scoring_mode: str = "baseline_v1"
    metric_deviation_score: Optional[float] = None
    log_evidence_score: Optional[float] = None
    trace_bottleneck_score: Optional[float] = None


class EvidencePackage(BaseModel):
    """Deterministic, verified, sanitized evidence package passed to Gemini or inspection."""
    model_config = ConfigDict(extra="forbid")

    package_version: str = "2.0"
    correlation_group_id: UUID
    project_id: UUID
    project_slug: str
    project_name: str
    time_window_start: datetime
    time_window_end: datetime
    confidence_score: float
    topology_complete: bool
    topology_status_explanation: str
    participating_events: List[EvidenceEventItem]
    service_dependencies: List[EvidenceDependencyItem]
    ranked_candidates: List[EvidenceCandidateItem]
    missing_evidence: List[str] = Field(default_factory=list)
    unobserved_telemetry: List[str] = Field(default_factory=list)
    signal_coverage: Optional[SignalCoverageSummary] = None
    metric_evidence: List[ServiceMetricEvidence] = Field(default_factory=list)
    log_evidence: List[CorrelatedLogHighlight] = Field(default_factory=list)
    trace_bottlenecks: List[BottleneckSpanEvidence] = Field(default_factory=list)
    multi_signal_timeline: List[MultiSignalTimelineEntry] = Field(default_factory=list)
    contradictory_signals: List[str] = Field(default_factory=list)
    neutral_signals: List[str] = Field(default_factory=list)
    primary_suspected_operation: Optional[str] = None
    affected_downstream_services: List[str] = Field(default_factory=list)
    source_evidence_snapshot_hash: Optional[str] = None
    evidence_hash: str


class TimelineEvidenceEvent(BaseModel):
    """Timeline event grounded in an actual anomaly event."""
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(..., description="Timestamp of the observed anomaly event (UTC)")
    event_id: UUID = Field(..., description="UUID referencing an actual AnomalyEvent record")
    service_id: UUID = Field(..., description="UUID of the affected service")
    service_name: str = Field(..., min_length=1, max_length=128)
    metric_name: str = Field(..., min_length=1, max_length=128)
    observation: str = Field(..., min_length=1)
    severity: str = Field(..., min_length=1)


class RootCauseEvidenceExplanation(BaseModel):
    """Root-cause explanation referencing a deterministic candidate."""
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID = Field(..., description="UUID referencing an existing RootCauseCandidate")
    service_id: UUID = Field(..., description="UUID of the candidate service")
    service_name: str = Field(..., min_length=1, max_length=128)
    explanation: str = Field(..., min_length=10)
    contributing_factors: List[str] = Field(default_factory=list)


class EvidenceReference(BaseModel):
    """Reference identifying an actual persisted source telemetry record."""
    model_config = ConfigDict(extra="forbid")

    source_record_type: str = Field(
        ...,
        description="anomaly_event, service_dependency, root_cause_candidate, correlation_group, baseline, metric_summary, application_log, or trace_span",
    )
    source_id: Union[UUID, str] = Field(..., description="ID of the cited source record (UUID, span_id, trace_id, or service_id:metric)")
    supported_field: str = Field(..., description="Field cited from source record (e.g. deviation_pct, self_time_ms, level)")
    summary_citation: str = Field(..., min_length=5)


class UncertaintyGap(BaseModel):
    """Explicitly declared uncertainty or unobserved variable in telemetry."""
    model_config = ConfigDict(extra="forbid")

    category: str = Field(..., description="missing_telemetry, unmapped_topology, unobserved_metric")
    description: str = Field(..., min_length=5)
    impact_on_confidence: str = Field(..., min_length=5)


class InvestigationStep(BaseModel):
    """Prioritized next diagnostic step for human SRE."""
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(..., ge=1)
    target_service: str = Field(..., min_length=1)
    action: str = Field(..., min_length=5)
    purpose: str = Field(..., min_length=5)


class RemediationRecommendation(BaseModel):
    """Safe remediation recommendation with mandatory human approval guard."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=5, max_length=256)
    action_type: RemediationActionType = Field(...)
    target_service: str = Field(..., min_length=1)
    description: str = Field(..., min_length=10)
    risk_level: RiskLevel = Field(...)
    preconditions: List[str] = Field(..., min_length=1)
    rollback_procedure: str = Field(..., min_length=5)
    requires_human_approval: bool = Field(
        default=True,
        description="Mandatory human approval flag; strictly cannot be False",
    )
    command_snippet: Optional[str] = Field(
        default=None,
        description="Autonomous execution is prohibited in Phase 3",
    )
    expected_result: Optional[str] = Field(
        default=None,
        description="Expected observable telemetry outcome if applied",
    )
    verification_steps: List[str] = Field(
        default_factory=list,
        description="How an engineer can verify whether the remediation succeeded",
    )

    @field_validator("requires_human_approval")
    @classmethod
    def enforce_human_approval(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("Remediation actions strictly require human approval (requires_human_approval must be True).")
        return v

    @field_validator("command_snippet")
    @classmethod
    def forbid_executable_snippets(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() != "":
            raise ValueError("Autonomous execution and executable command snippets are strictly prohibited in Sprint 5.1.")
        return None


class InvestigationResult(BaseModel):
    """Complete validated result payload synthesized from grounded telemetry evidence."""
    model_config = ConfigDict(extra="forbid")

    incident_summary: str = Field(..., min_length=20)
    conclusion_status: str = Field(
        default="CONCLUSIVE",
        description="CONCLUSIVE, CORRELATION_ONLY, or INCONCLUSIVE",
    )
    confidence_level: str = Field(
        default="MEDIUM",
        description="HIGH, MEDIUM, or LOW",
    )
    confidence_explanation: Optional[str] = Field(
        default=None,
        description="Why the stated confidence level is appropriate given signal quality and gaps",
    )
    suspected_operation: Optional[str] = Field(
        default=None,
        description="Most likely responsible endpoint/operation if supported by trace/log evidence",
    )
    timeline: List[TimelineEvidenceEvent] = Field(..., min_length=1)
    root_cause_analysis: RootCauseEvidenceExplanation = Field(...)
    alternative_explanations: List[str] = Field(default_factory=list)
    evidence_references: List[EvidenceReference] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    neutral_evidence: List[str] = Field(default_factory=list)
    uncertainties_and_gaps: List[UncertaintyGap] = Field(default_factory=list)
    prioritized_investigation_steps: List[InvestigationStep] = Field(default_factory=list)
    remediation_recommendations: List[RemediationRecommendation] = Field(default_factory=list)


class InvestigationGenerateRequest(BaseModel):
    """Request payload to initiate grounded incident investigation."""
    model_config = ConfigDict(extra="forbid")

    correlation_group_id: UUID = Field(..., description="Correlation group to investigate")
    force_regenerate: bool = Field(
        default=False,
        description="Force re-running investigation even if an existing COMPLETED investigation exists",
    )


class GroundedInvestigationResponse(BaseModel):
    """Investigation record response including provenance and validation metadata."""
    id: UUID
    correlation_group_id: Optional[UUID] = None
    incident_id: Optional[UUID] = None
    provider: str
    model_name: str
    prompt_version: str
    schema_version: str
    status: str
    evidence_hash: Optional[str] = None
    evidence_stale: bool = False
    latest_evidence_hash: Optional[str] = None
    result: Optional[InvestigationResult] = None
    investigation_json: Optional[Dict[str, Any]] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def populate_result_from_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "result" not in data and "investigation_json" in data:
                data["result"] = data["investigation_json"]
            elif "investigation_json" not in data and "result" in data:
                data["investigation_json"] = data["result"]
            return data
        elif hasattr(data, "investigation_json"):
            raw = getattr(data, "investigation_json")
            return {
                "id": getattr(data, "id"),
                "correlation_group_id": getattr(data, "correlation_group_id", None),
                "incident_id": getattr(data, "incident_id", None),
                "provider": getattr(data, "provider", "google-gemini"),
                "model_name": getattr(data, "model_name", "gemini-2.0-flash"),
                "prompt_version": getattr(data, "prompt_version", "v1.0"),
                "schema_version": getattr(data, "schema_version", "v1.0"),
                "status": getattr(data, "status", "PENDING"),
                "evidence_hash": getattr(data, "evidence_hash", None),
                "result": raw,
                "investigation_json": raw,
                "prompt_tokens": getattr(data, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(data, "completion_tokens", 0) or 0,
                "total_tokens": getattr(data, "total_tokens", 0) or 0,
                "latency_ms": getattr(data, "latency_ms", 0) or 0,
                "error_message": getattr(data, "error_message", None),
                "started_at": getattr(data, "started_at", None),
                "completed_at": getattr(data, "completed_at", None),
                "created_at": getattr(data, "created_at", None),
                "updated_at": getattr(data, "updated_at", None),
            }
        return data


# --- Legacy Phase 2.3A Seed Schemas ---

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

