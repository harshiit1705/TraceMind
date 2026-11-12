"""Pydantic v2 schemas for anomaly correlation, root-cause ranking, and explainability."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CorrelationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class RankingConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CorrelationConfig(BaseModel):
    """Configuration parameters for cross-service anomaly correlation."""
    time_window_seconds: int = Field(
        default=300,
        ge=30,
        le=7200,
        description="Sliding or bounding time window (seconds) within which anomalies may correlate.",
    )
    max_events: int = Field(
        default=100,
        ge=2,
        le=500,
        description="Maximum number of anomaly events to evaluate per correlation pass.",
    )
    min_events_per_group: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Minimum number of related anomaly events required to form a correlation group.",
    )
    max_cascade_delay_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Maximum temporal gap (seconds) between causally related anomalies across dependent services.",
    )
    max_incident_duration_seconds: Optional[int] = Field(
        default=None,
        ge=10,
        le=7200,
        description=(
            "Maximum total time span (seconds) between the earliest and latest anomaly in a correlation group. "
            "If None, defaults to max_cascade_delay_seconds to prevent temporal chaining."
        ),
    )

    @model_validator(mode="after")
    def validate_duration_bounds(self) -> "CorrelationConfig":
        if self.max_incident_duration_seconds is not None:
            if self.max_incident_duration_seconds < self.max_cascade_delay_seconds:
                self.max_incident_duration_seconds = self.max_cascade_delay_seconds
        return self


class CorrelationEvaluationRequest(BaseModel):
    """Request payload to trigger cross-service anomaly correlation evaluation."""
    project_id: UUID = Field(
        ...,
        description="Project boundary for isolated correlation analysis.",
    )
    start_time: Optional[datetime] = Field(
        default=None,
        description="Start of evaluation time window (UTC). If omitted, defaults to now - time_window_seconds.",
    )
    end_time: Optional[datetime] = Field(
        default=None,
        description="End of evaluation time window (UTC). If omitted, defaults to now.",
    )
    config: Optional[CorrelationConfig] = Field(
        default=None,
        description="Optional correlation configuration overrides.",
    )

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_utc_tz(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("Evaluation timestamps must be timezone-aware (e.g. UTC).")
        return v


class RankingDimensionScore(BaseModel):
    """Breakdown of an individual scoring dimension in the root-cause ranking algorithm."""
    score: float = Field(..., ge=0.0, le=1.0, description="Normalized score (0.0 to 1.0).")
    weight: float = Field(..., ge=0.0, le=1.0, description="Relative algorithm weight.")
    weighted_score: float = Field(..., ge=0.0, le=1.0, description="score * weight.")
    reason: str = Field(..., description="Deterministic human-readable justification.")
    available: bool = Field(
        default=True,
        description="False when underlying signal data was absent (no missing-signal penalty applied).",
    )


class RootCauseRankingBreakdown(BaseModel):
    """Transparent ranking breakdown across deterministic causal & telemetry dimensions."""
    temporal_precedence: RankingDimensionScore
    topological_position: RankingDimensionScore
    blast_radius: RankingDimensionScore
    severity_magnitude: RankingDimensionScore
    metric_deviation: Optional[RankingDimensionScore] = None
    log_evidence: Optional[RankingDimensionScore] = None
    trace_bottleneck: Optional[RankingDimensionScore] = None


class SignalCoverageSummary(BaseModel):
    """Availability and volume of each observability signal in the evaluation window."""
    metrics_available: bool = False
    logs_available: bool = False
    traces_available: bool = False
    topology_available: bool = False
    anomalies_count: int = 0
    metric_samples_count: int = 0
    log_entries_count: int = 0
    error_logs_count: int = 0
    trace_spans_count: int = 0
    traces_count: int = 0
    incomplete_traces_count: int = 0
    observed_signals: List[str] = Field(default_factory=list)
    missing_signals: List[str] = Field(default_factory=list)


class ServiceMetricEvidence(BaseModel):
    """Bounded statistical comparison of persisted metrics against baseline for a service."""
    service_id: UUID
    service_slug: str
    service_name: str
    metric_name: str
    metric_unit: str = ""
    sample_count: int
    baseline_sample_count: int = 0
    min_value: float
    max_value: float
    mean_value: float
    p95_value: Optional[float] = None
    baseline_mean: Optional[float] = None
    deviation_pct: Optional[float] = None
    is_anomalous: bool = False
    status: str = "normal"  # anomalous | normal | insufficient_samples
    first_breach_at: Optional[datetime] = None


class CorrelatedLogHighlight(BaseModel):
    """Sanitized representative structured log entry correlated to the incident window or trace."""
    log_id: UUID
    service_id: UUID
    service_slug: str
    service_name: str
    timestamp: datetime
    level: str
    message: str
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    exception_type: Optional[str] = None
    pattern_category: Optional[str] = None


class BottleneckSpanEvidence(BaseModel):
    """Trace span bottleneck / origin error record computed via exclusive self-time analysis."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    service_id: UUID
    service_slug: str
    service_name: str
    operation_name: str
    span_kind: str
    duration_ms: float
    self_time_ms: float
    self_time_share: float
    status: str
    http_status_code: Optional[int] = None
    error_message: Optional[str] = None
    start_time: datetime
    is_origin_error: bool = False
    is_bottleneck: bool = False
    has_missing_parent: bool = False


class MultiSignalTimelineEntry(BaseModel):
    """Chronological merged timeline item across anomalies, metrics, logs, and traces."""
    timestamp: datetime
    signal_type: str  # anomaly | metric | log | trace
    service_id: UUID
    service_slug: str
    service_name: str
    severity: str
    title: str
    detail: str
    reference_id: Optional[str] = None


class MultiSignalEvidenceSummary(BaseModel):
    """Canonical bounded snapshot of multi-signal evidence for a correlation group."""
    correlation_group_id: Optional[UUID] = None
    project_id: UUID
    time_window_start: datetime
    time_window_end: datetime
    evidence_version: str = "2.0"
    evidence_hash: Optional[str] = None
    computed_at: datetime
    coverage: SignalCoverageSummary
    metric_summaries: List[ServiceMetricEvidence] = Field(default_factory=list)
    log_highlights: List[CorrelatedLogHighlight] = Field(default_factory=list)
    trace_bottlenecks: List[BottleneckSpanEvidence] = Field(default_factory=list)
    timeline: List[MultiSignalTimelineEntry] = Field(default_factory=list)
    primary_suspected_operation: Optional[str] = None
    affected_downstream_services: List[str] = Field(default_factory=list)
    contradictory_signals: List[str] = Field(default_factory=list)
    neutral_signals: List[str] = Field(default_factory=list)
    missing_signals: List[str] = Field(default_factory=list)
    uncertainty_notes: List[str] = Field(default_factory=list)


class RootCauseCandidateResponse(BaseModel):
    """Ranked root cause candidate with full explainability and confidence flags."""
    rank: int = Field(..., ge=1, description="Rank 1 is the most probable initiator.")
    service_id: UUID
    service_slug: str
    service_name: str
    service_identifier: str
    score: float = Field(..., ge=0.0, le=1.0, description="Deterministic composite score (0.0 - 1.0).")
    confidence: RankingConfidence
    is_probable_root_cause: bool = Field(
        ...,
        description="True for top probable root-cause candidate(s). Not a claim of proven causation.",
    )
    breakdown: RootCauseRankingBreakdown
    supporting_evidence: List[str]
    limitations: List[str]
    contradictory_evidence: List[str] = Field(default_factory=list)
    neutral_signals: List[str] = Field(default_factory=list)
    missing_signals: List[str] = Field(default_factory=list)
    primary_suspected_operation: Optional[str] = None
    affected_downstream_services: List[str] = Field(default_factory=list)
    evidence_references: Dict[str, Any] = Field(default_factory=dict)
    scoring_mode: str = "baseline_v1"

    model_config = ConfigDict(from_attributes=True)


class CorrelatedEventSummary(BaseModel):
    """Summary of an anomaly event participating in a correlation group."""
    event_id: UUID
    service_id: UUID
    service_name: str
    service_identifier: str
    metric_name: str
    observed_value: float
    expected_baseline: Optional[float] = None
    deviation_pct: Optional[float] = None
    severity: str
    occurred_at: datetime
    relevance_score: float
    correlation_reason: str

    model_config = ConfigDict(from_attributes=True)


class CorrelationGroupResponse(BaseModel):
    """Response representing a correlated group of anomaly events and ranked root causes."""
    id: UUID
    project_id: UUID
    correlation_key: str
    time_window_start: datetime
    time_window_end: datetime
    status: str
    summary: Optional[str] = None
    confidence_score: float
    topology_complete: bool
    events_count: int
    participating_events: List[CorrelatedEventSummary]
    ranked_candidates: List[RootCauseCandidateResponse]
    evidence_summary: Optional[MultiSignalEvidenceSummary] = None
    primary_suspected_operation: Optional[str] = None
    uncertainty_summary: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CorrelationEvaluationResponse(BaseModel):
    """Response returned by the evaluation endpoint containing all discovered correlation groups."""
    project_id: UUID
    evaluated_at: datetime
    time_window_start: datetime
    time_window_end: datetime
    total_anomalies_evaluated: int
    correlation_groups_count: int
    groups: List[CorrelationGroupResponse]

