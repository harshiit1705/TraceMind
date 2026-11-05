from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DetectionMethod(str, Enum):
    ROLLING_AVERAGE = "rolling_average"
    EWMA = "ewma"


class DetectionStatus(str, Enum):
    WARMING_UP = "WARMING_UP"
    NORMAL = "NORMAL"
    ANOMALY = "ANOMALY"


class AnomalySeverity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AnomalyEventStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class MetricType(str, Enum):
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    REQUEST_RATE = "request_rate"


class AnomalyDetectionConfig(BaseModel):
    """Configuration options for statistical anomaly detection."""
    method: DetectionMethod = Field(default=DetectionMethod.ROLLING_AVERAGE, description="Baseline computation method")
    window_size: int = Field(default=10, ge=1, le=1000, description="Rolling window sample capacity")
    min_samples: int = Field(default=3, ge=1, description="Minimum samples required before detection is enabled")
    alpha: float = Field(default=0.3, gt=0.0, le=1.0, description="EWMA weighting factor between (0, 1]")
    threshold_pct: float = Field(default=30.0, gt=0.0, description="Strictly positive percentage deviation threshold")
    threshold_abs: float = Field(default=1.0, gt=0.0, description="Strictly positive absolute deviation threshold")
    bidirectional: bool = Field(default=False, description="Whether both positive and negative deviations trigger anomalies")

    @field_validator("window_size", "min_samples", "alpha", "threshold_pct", "threshold_abs", mode="before")
    @classmethod
    def reject_boolean_configuration_values(cls, value):
        # bool is a subclass of int in Python; do not allow True/False to be
        # silently coerced into numeric detector configuration.
        if isinstance(value, bool):
            raise ValueError("Boolean values are not valid numeric detector configuration.")
        return value

    model_config = ConfigDict(frozen=True)


class AnomalyDetectionResult(BaseModel):
    """Structured result returned by the anomaly detection engine."""
    is_anomaly: bool = Field(..., description="True if observed value exceeds threshold deviation in ready state")
    detection_status: DetectionStatus = Field(default=DetectionStatus.NORMAL, description="Current detection lifecycle status")
    metric_name: str = Field(..., description="Name of the metric evaluated (e.g. latency, error_rate)")
    observed_value: float = Field(..., description="The evaluated measurement value")
    expected_baseline: Optional[float] = Field(default=None, description="Computed expected normal baseline, if ready")
    deviation_pct: Optional[float] = Field(default=None, description="Percentage deviation from baseline where meaningful")
    severity: AnomalySeverity = Field(default=AnomalySeverity.NONE, description="Assessed severity of detected anomaly")
    detection_method: DetectionMethod = Field(..., description="Method used to calculate baseline and deviation")
    explanation: str = Field(..., description="Human-readable explanation of detection verdict")
    sample_count: int = Field(default=0, ge=0, description="Number of baseline samples available at evaluation time")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of evaluation")

    model_config = ConfigDict(from_attributes=True)


class AnomalyEvaluationRequest(BaseModel):
    """API payload for evaluating a telemetry measurement."""
    project_id: UUID = Field(..., description="UUID of the parent project")
    service_identifier: str = Field(..., min_length=1, max_length=128, description="Identifier or slug of the service")
    metric_name: str = Field(..., min_length=1, max_length=64, description="Metric identifier, e.g. latency, error_rate")
    observed_value: float = Field(..., description="Numerical telemetry measurement value")
    timestamp: Optional[datetime] = Field(default=None, description="Optional measurement timestamp (defaults to now)")
    source_event_id: Optional[str] = Field(default=None, max_length=128, description="Optional unique telemetry event identifier for idempotency")

    @field_validator("observed_value", mode="before")
    @classmethod
    def reject_boolean_values(cls, v):
        if isinstance(v, bool):
            raise ValueError("observed_value must be a finite numerical float or int, not a boolean.")
        return v

    @field_validator("service_identifier", "metric_name")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("String fields must not be empty or whitespace.")
        return v.strip()

    @field_validator("timestamp")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone offset (for example, Z or +05:30).")
        return value.astimezone(timezone.utc)


class AnomalyEvaluationResponse(BaseModel):
    """API response contract for anomaly evaluation."""
    is_anomaly: bool
    detection_status: DetectionStatus
    service_identifier: str
    metric_name: str
    observed_value: float
    expected_baseline: Optional[float]
    deviation_pct: Optional[float]
    severity: AnomalySeverity
    detection_method: DetectionMethod
    sample_count: int
    explanation: str
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)
