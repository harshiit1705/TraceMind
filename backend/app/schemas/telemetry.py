"""Pydantic v2 schemas for metrics, structured application logs, and distributed traces."""

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _ensure_utc_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware (UTC ISO-8601).")
    return dt.astimezone(timezone.utc)


def _reject_bool_and_nonfinite(v: Any, field_name: str = "value") -> float:
    if isinstance(v, bool):
        raise ValueError(f"{field_name} must be numeric, not boolean.")
    val = float(v)
    if not math.isfinite(val):
        raise ValueError(f"{field_name} must be a finite number.")
    return val


# --- Metrics Schemas (Milestone 6.1) ---


class MetricSampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_identifier: str = Field(..., min_length=1, max_length=128)
    metric_name: str = Field(..., min_length=1, max_length=64)
    metric_unit: str = Field(default="", max_length=32)
    value: float
    timestamp: Optional[datetime] = None
    endpoint: Optional[str] = Field(default=None, max_length=256)
    http_status_code: Optional[int] = Field(default=None, ge=100, le=599)
    request_id: Optional[str] = Field(default=None, max_length=128)
    trace_id: Optional[str] = Field(default=None, max_length=64)
    source_event_id: Optional[str] = Field(default=None, max_length=128)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    evaluate_anomaly: bool = Field(
        default=True,
        description="Forward eligible canonical metrics to AnomalyService without duplicate evaluation.",
    )

    @field_validator("value", mode="before")
    @classmethod
    def validate_value_finite(cls, v: Any) -> float:
        return _reject_bool_and_nonfinite(v, "value")

    @field_validator("metric_name")
    @classmethod
    def normalize_metric_name(cls, v: str) -> str:
        norm = v.strip().lower()
        if not norm:
            raise ValueError("metric_name cannot be empty.")
        return norm

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _ensure_utc_datetime(v)

    @model_validator(mode="after")
    def validate_metric_domain(self):
        name = self.metric_name
        if ("latency" in name or "request_rate" in name or "request_count" in name or "memory" in name) and self.value < 0.0:
            raise ValueError(f"Metric '{name}' cannot be negative (got {self.value}).")
        if "error_rate" in name and (self.value < 0.0 or self.value > 100.0):
            raise ValueError(f"Metric '{name}' percentage must be between 0.0 and 100.0 (got {self.value}).")
        if "cpu" in name and (self.value < 0.0 or self.value > 100.0 * 64):
            # Allow multi-core process CPU% while rejecting negative or absurd values
            raise ValueError(f"Metric '{name}' must be non-negative and within valid bounds (got {self.value}).")
        return self


class MetricBatchIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    samples: List[MetricSampleInput] = Field(..., min_length=1, max_length=100)


class MetricIngestResultItem(BaseModel):
    id: Optional[UUID] = None
    service_identifier: str
    metric_name: str
    persisted: bool
    duplicate: bool = False
    anomaly_evaluated: bool = False
    is_anomaly: bool = False
    anomaly_severity: Optional[str] = None
    anomaly_note: Optional[str] = None


class MetricBatchIngestResponse(BaseModel):
    accepted_count: int
    duplicate_count: int
    anomalies_detected_count: int
    results: List[MetricIngestResultItem]


class MetricSampleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    service_id: UUID
    service_slug: Optional[str] = None
    service_name: Optional[str] = None
    metric_name: str
    metric_unit: str
    value: float
    timestamp: datetime
    endpoint: Optional[str] = None
    http_status_code: Optional[int] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    source_event_id: Optional[str] = None
    attributes_json: Dict[str, Any] = Field(default_factory=dict)


class TelemetryTimeSeriesPointResponse(BaseModel):
    time: str
    timestamp: int
    throughputRps: Optional[float] = 0.0
    baselineThroughputRps: Optional[float] = None
    throughputAvailable: bool = False
    requestCount: int = 0
    metricSamplesCount: int = 0
    errorRatePercent: float
    p50Ms: float
    p90Ms: float
    p95Ms: float
    p99Ms: float
    isAnomaly: bool = False


class TelemetryOverviewResponse(BaseModel):
    timeRange: str
    points: List[TelemetryTimeSeriesPointResponse]
    currentThroughputRps: Optional[float] = 0.0
    meanThroughputRps: Optional[float] = 0.0
    peakThroughputRps: Optional[float] = 0.0
    throughputAvailable: bool = False
    requestRateStatus: Literal["available", "no_traffic", "insufficient_data"] = "no_traffic"
    totalRequests: int = 0
    totalMetricSamples: int = 0
    sampleIngestionRatePerSec: Optional[float] = None
    currentErrorRatePercent: float
    peakErrorRatePercent: float
    currentP95Ms: float
    baselineP95Ms: float
    currentP99Ms: float


# --- Structured Application Logs Schemas (Milestone 6.2) ---


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ApplicationLogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_identifier: str = Field(..., min_length=1, max_length=128)
    timestamp: Optional[datetime] = None
    level: str = Field(default="INFO", max_length=16)
    message: str = Field(..., min_length=1, max_length=8192)
    request_id: Optional[str] = Field(default=None, max_length=128)
    trace_id: Optional[str] = Field(default=None, max_length=64)
    span_id: Optional[str] = Field(default=None, max_length=32)
    source_event_id: Optional[str] = Field(default=None, max_length=128)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    exception_type: Optional[str] = Field(default=None, max_length=128)
    exception_message: Optional[str] = Field(default=None, max_length=4096)

    @field_validator("level")
    @classmethod
    def normalize_level(cls, v: str) -> str:
        norm = v.strip().upper()
        if norm == "WARN":
            norm = "WARNING"
        if norm not in {lvl.value for lvl in LogLevel}:
            raise ValueError(f"Unsupported log level '{v}'. Allowed: DEBUG, INFO, WARNING, ERROR, CRITICAL.")
        return norm

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _ensure_utc_datetime(v)


class LogBatchIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    logs: List[ApplicationLogInput] = Field(..., min_length=1, max_length=100)


class LogBatchIngestResponse(BaseModel):
    accepted_count: int
    duplicate_count: int
    log_ids: List[UUID]


class ApplicationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    service_id: UUID
    service_slug: Optional[str] = None
    service_name: Optional[str] = None
    timestamp: datetime
    level: str
    message: str
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    source_event_id: Optional[str] = None
    attributes_json: Dict[str, Any] = Field(default_factory=dict)
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None


# --- Distributed Tracing Schemas (Milestone 6.3) ---


class SpanKind(str, Enum):
    SERVER = "server"
    CLIENT = "client"
    INTERNAL = "internal"
    DATABASE = "database"


class SpanStatusEnum(str, Enum):
    OK = "ok"
    ERROR = "error"


class TraceSpanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_identifier: str = Field(..., min_length=1, max_length=128)
    trace_id: str = Field(..., min_length=8, max_length=64)
    span_id: str = Field(..., min_length=4, max_length=32)
    parent_span_id: Optional[str] = Field(default=None, min_length=4, max_length=32)
    operation_name: str = Field(..., min_length=1, max_length=256)
    span_kind: SpanKind = Field(default=SpanKind.SERVER)
    start_time: datetime
    end_time: datetime
    duration_ms: Optional[float] = None
    status: SpanStatusEnum = Field(default=SpanStatusEnum.OK)
    http_status_code: Optional[int] = Field(default=None, ge=100, le=599)
    error_message: Optional[str] = Field(default=None, max_length=2048)
    request_id: Optional[str] = Field(default=None, max_length=128)
    attributes: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_times(cls, v: datetime) -> datetime:
        res = _ensure_utc_datetime(v)
        assert res is not None
        return res

    @field_validator("duration_ms", mode="before")
    @classmethod
    def validate_duration(cls, v: Any) -> Optional[float]:
        if v is None:
            return None
        val = _reject_bool_and_nonfinite(v, "duration_ms")
        if val < 0.0:
            raise ValueError("duration_ms cannot be negative.")
        return val

    @model_validator(mode="after")
    def validate_span_consistency(self):
        if self.end_time < self.start_time:
            raise ValueError("end_time must be greater than or equal to start_time.")
        if self.parent_span_id and self.parent_span_id == self.span_id:
            raise ValueError("parent_span_id cannot equal span_id (self-cycle).")
        if self.duration_ms is None:
            self.duration_ms = round((self.end_time - self.start_time).total_seconds() * 1000.0, 3)
        return self


class SpanBatchIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    spans: List[TraceSpanInput] = Field(..., min_length=1, max_length=100)


class SpanBatchIngestResponse(BaseModel):
    accepted_count: int
    duplicate_count: int
    span_ids: List[UUID]


class WaterfallSpanResponse(BaseModel):
    """Frontend-compatible span item matching SpanItem waterfall structure."""
    id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: str
    service: str
    service_slug: str
    operation: str
    span_kind: str
    start_time: datetime
    end_time: datetime
    durationMs: float
    offsetPercent: float
    widthPercent: float
    status: str
    httpStatus: Optional[int] = None
    isBottleneck: bool = False
    depth: int = 0
    hasChildren: bool = False
    request_id: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    exception: Optional[Dict[str, Any]] = None


class TraceSummaryResponse(BaseModel):
    """Frontend-compatible trace summary matching TraceItem structure."""
    id: str
    project_id: UUID
    rootService: str
    rootServiceSlug: str
    rootEndpoint: str
    durationMs: float
    spansCount: int
    status: str
    statusCode: int
    timestamp: datetime
    anomalous: bool
    spans: Optional[List[WaterfallSpanResponse]] = None


class TraceListResponse(BaseModel):
    items: List[TraceSummaryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

