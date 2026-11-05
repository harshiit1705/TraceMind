"""Thread-safe statistical anomaly detection for application telemetry."""

import math
import statistics
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

from app.schemas.anomaly import (
    AnomalyDetectionConfig,
    AnomalyDetectionResult,
    AnomalySeverity,
    DetectionMethod,
    DetectionStatus,
    MetricType,
)
from app.services.anomaly.baseline import EWMABaseline, RollingBaseline


Baseline = Union[RollingBaseline, EWMABaseline]


class OutOfOrderMeasurementError(ValueError):
    """Raised when a measurement timestamp is not newer than the last one."""


class AnomalyDetector:
    """Process-local, atomic detector for one service/metric registry entry.

    Warmup uses a small batch of candidate observations. Once min_samples
    candidates are available, candidates that exceed the configured percentage
    threshold from their batch median are excluded. If fewer than min_samples
    remain, the accepted candidates are retained and warmup continues.

    Timestamps are event-time watermarks: each accepted evaluation must be
    strictly newer than the previous evaluation for this detector. Missing
    timestamps are generated in UTC and made monotonic within this process.
    """

    def __init__(self, config: Optional[AnomalyDetectionConfig] = None):
        self.config = config or AnomalyDetectionConfig()
        if isinstance(self.config.threshold_pct, bool) or self.config.threshold_pct <= 0.0:
            raise ValueError("threshold_pct must be strictly positive and numeric")
        if isinstance(self.config.threshold_abs, bool) or self.config.threshold_abs <= 0.0:
            raise ValueError("threshold_abs must be strictly positive and numeric")

        self._baselines: Dict[str, Baseline] = {}
        self._warmup_candidates: Dict[str, List[float]] = {}
        self._last_timestamps: Dict[str, datetime] = {}
        self._persisted_version: int = 0
        self._lock = threading.RLock()

    @staticmethod
    def normalize_metric_name(metric_name: str) -> str:
        if not isinstance(metric_name, str) or not metric_name.strip():
            raise ValueError("Metric name must be a non-empty string.")
        return metric_name.strip().lower()

    @staticmethod
    def _normalize_timestamp(timestamp: Optional[datetime]) -> datetime:
        if timestamp is None:
            return datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware.")
        return timestamp.astimezone(timezone.utc)

    def _next_timestamp(self, metric_name: str, timestamp: Optional[datetime]) -> datetime:
        normalized = self._normalize_timestamp(timestamp)
        previous = self._last_timestamps.get(metric_name)
        if timestamp is None and previous is not None and normalized <= previous:
            normalized = previous + timedelta(microseconds=1)
        elif previous is not None and normalized <= previous:
            raise OutOfOrderMeasurementError(
                "timestamp must be strictly newer than the previous measurement "
                "for this project/service/metric. Duplicate and out-of-order measurements are rejected."
            )
        return normalized

    def _get_or_create_baseline(self, metric_name: str) -> Baseline:
        key = self.normalize_metric_name(metric_name)
        if key not in self._baselines:
            if self.config.method == DetectionMethod.EWMA:
                self._baselines[key] = EWMABaseline(
                    alpha=self.config.alpha,
                    min_samples=self.config.min_samples,
                )
            else:
                self._baselines[key] = RollingBaseline(
                    window_size=self.config.window_size,
                    min_samples=self.config.min_samples,
                )
        return self._baselines[key]

    def _validate_input(self, metric_name: str, value: float) -> str:
        key = self.normalize_metric_name(metric_name)
        if isinstance(value, bool):
            raise ValueError(f"Measurement for '{key}' cannot be a boolean: {value}")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Measurement for '{key}' must be a finite number, got: {value}")
        if MetricType.LATENCY.value in key and value < 0.0:
            raise ValueError(f"Latency cannot be negative, got: {value}")
        if MetricType.ERROR_RATE.value in key and (value < 0.0 or value > 100.0):
            raise ValueError(f"Error rate percentage must be between 0.0 and 100.0, got: {value}")
        if MetricType.REQUEST_RATE.value in key and value < 0.0:
            raise ValueError(f"Request rate cannot be negative, got: {value}")
        return key

    def _calculate_severity(self, deviation_ratio: float) -> AnomalySeverity:
        if deviation_ratio >= 4.0:
            return AnomalySeverity.CRITICAL
        if deviation_ratio >= 2.5:
            return AnomalySeverity.HIGH
        if deviation_ratio >= 1.5:
            return AnomalySeverity.MEDIUM
        return AnomalySeverity.LOW

    def get_baseline_value(self, metric_name: str) -> Optional[float]:
        with self._lock:
            return self._get_or_create_baseline(metric_name).value

    def get_sample_count(self, metric_name: str) -> int:
        with self._lock:
            key = self.normalize_metric_name(metric_name)
            baseline = self._get_or_create_baseline(key)
            return baseline.sample_count + len(self._warmup_candidates.get(key, []))

    def update_baseline(self, metric_name: str, value: float) -> None:
        key = self._validate_input(metric_name, value)
        with self._lock:
            self._warmup_candidates.pop(key, None)
            self._get_or_create_baseline(key).add(float(value))

    def _evaluate_unlocked(
        self, metric_name: str, observed_value: float, timestamp: datetime
    ) -> AnomalyDetectionResult:
        key = self._validate_input(metric_name, observed_value)
        val = float(observed_value)
        baseline = self._get_or_create_baseline(key)
        sample_count = baseline.sample_count + len(self._warmup_candidates.get(key, []))

        if not baseline.is_ready or baseline.value is None:
            return AnomalyDetectionResult(
                is_anomaly=False,
                detection_status=DetectionStatus.WARMING_UP,
                metric_name=key,
                observed_value=val,
                expected_baseline=None,
                deviation_pct=None,
                severity=AnomalySeverity.NONE,
                detection_method=self.config.method,
                explanation=(
                    f"Baseline warming up (insufficient accepted samples: "
                    f"{sample_count}/{self.config.min_samples}) for '{key}'. "
                    "Anomaly detection inactive."
                ),
                sample_count=sample_count,
                timestamp=timestamp,
            )

        expected = baseline.value
        if expected == 0.0:
            if val == 0.0:
                return AnomalyDetectionResult(
                    is_anomaly=False, detection_status=DetectionStatus.NORMAL,
                    metric_name=key, observed_value=val, expected_baseline=0.0,
                    deviation_pct=0.0, severity=AnomalySeverity.NONE,
                    detection_method=self.config.method,
                    explanation=f"Observed value 0.0 matches zero baseline for '{key}'.",
                    sample_count=sample_count, timestamp=timestamp,
                )
            abs_diff = abs(val)
            is_anomaly = abs_diff >= self.config.threshold_abs
            severity = self._calculate_severity(abs_diff / self.config.threshold_abs) if is_anomaly else AnomalySeverity.NONE
            explanation = (
                f"Observed value {val:.2f} deviated from zero baseline by {abs_diff:.2f} "
                f"(exceeds absolute threshold {self.config.threshold_abs:.2f})."
                if is_anomaly else
                f"Observed value {val:.2f} from zero baseline within absolute tolerance {self.config.threshold_abs:.2f}."
            )
            return AnomalyDetectionResult(
                is_anomaly=is_anomaly,
                detection_status=DetectionStatus.ANOMALY if is_anomaly else DetectionStatus.NORMAL,
                metric_name=key, observed_value=val, expected_baseline=0.0,
                deviation_pct=None, severity=severity, detection_method=self.config.method,
                explanation=explanation, sample_count=sample_count, timestamp=timestamp,
            )

        deviation_pct = ((val - expected) / expected) * 100.0
        effective_deviation = abs(deviation_pct) if self.config.bidirectional else deviation_pct
        is_anomaly = effective_deviation >= self.config.threshold_pct
        if is_anomaly:
            severity = self._calculate_severity(effective_deviation / self.config.threshold_pct)
            direction = "exceeds" if deviation_pct >= 0 else "drops below"
            explanation = (
                f"Metric '{key}' value {val:.2f} {direction} baseline {expected:.2f} "
                f"by {deviation_pct:+.1f}% (threshold: {self.config.threshold_pct:.1f}%)."
            )
        else:
            severity = AnomalySeverity.NONE
            explanation = (
                f"Metric '{key}' value {val:.2f} is within acceptable baseline tolerance "
                f"({deviation_pct:+.1f}% vs threshold {self.config.threshold_pct:.1f}%)."
            )
        return AnomalyDetectionResult(
            is_anomaly=is_anomaly,
            detection_status=DetectionStatus.ANOMALY if is_anomaly else DetectionStatus.NORMAL,
            metric_name=key, observed_value=val, expected_baseline=expected,
            deviation_pct=round(deviation_pct, 2), severity=severity,
            detection_method=self.config.method, explanation=explanation,
            sample_count=sample_count, timestamp=timestamp,
        )

    def evaluate(
        self, metric_name: str, observed_value: float, timestamp: Optional[datetime] = None
    ) -> AnomalyDetectionResult:
        key = self._validate_input(metric_name, observed_value)
        event_timestamp = self._normalize_timestamp(timestamp)
        with self._lock:
            return self._evaluate_unlocked(key, observed_value, event_timestamp)

    def _warmup_accept(self, key: str, observed_value: float) -> bool:
        """Batch-filter warmup candidates around their median before seeding baseline."""
        candidates = self._warmup_candidates.setdefault(key, [])
        candidates.append(float(observed_value))
        if len(candidates) < self.config.min_samples:
            return False

        center = statistics.median(candidates)
        accepted = []
        for candidate in candidates:
            if center == 0.0:
                outlier = abs(candidate - center) >= self.config.threshold_abs
            else:
                pct = abs((candidate - center) / center) * 100.0
                outlier = pct >= self.config.threshold_pct
            if not outlier:
                accepted.append(candidate)

        # Seed the real baseline only after screening the complete warmup batch.
        if len(accepted) >= self.config.min_samples:
            baseline = self._get_or_create_baseline(key)
            for candidate in accepted:
                baseline.add(candidate)
            self._warmup_candidates.pop(key, None)
            return True

        # Keep only accepted candidates and continue collecting until ready.
        self._warmup_candidates[key] = accepted
        return False

    def evaluate_and_update(
        self,
        metric_name: str,
        observed_value: float,
        update_if_normal: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> AnomalyDetectionResult:
        """Atomically evaluate, advance event-time watermark, and update baseline."""
        key = self._validate_input(metric_name, observed_value)
        with self._lock:
            event_timestamp = self._next_timestamp(key, timestamp)
            baseline = self._get_or_create_baseline(key)
            if not baseline.is_ready:
                result = self._evaluate_unlocked(key, observed_value, event_timestamp)
                if update_if_normal:
                    became_ready = self._warmup_accept(key, observed_value)
                    if not became_ready and len(self._warmup_candidates.get(key, [])) < self.config.min_samples:
                        result.explanation = (
                            f"{result.explanation} Warmup candidates are being screened against "
                            "their median; rejected outliers do not enter the baseline."
                        )
                    elif became_ready:
                        result.explanation = (
                            f"{result.explanation} Robust warmup initialization completed; "
                            "median-inconsistent candidates were excluded."
                        )
                self._last_timestamps[key] = event_timestamp
                return result

            result = self._evaluate_unlocked(key, observed_value, event_timestamp)
            if update_if_normal and not result.is_anomaly:
                baseline.add(float(observed_value))
            self._last_timestamps[key] = event_timestamp
            return result

    def clear(self, metric_name: Optional[str] = None) -> None:
        with self._lock:
            if metric_name:
                key = self.normalize_metric_name(metric_name)
                baseline = self._baselines.get(key)
                if baseline is not None:
                    baseline.clear()
                self._warmup_candidates.pop(key, None)
                self._last_timestamps.pop(key, None)
            else:
                self._baselines.clear()
                self._warmup_candidates.clear()
                self._last_timestamps.clear()

    def get_last_timestamp(self, metric_name: str) -> Optional[datetime]:
        """Return the most recent processed event timestamp for the metric."""
        with self._lock:
            key = self.normalize_metric_name(metric_name)
            return self._last_timestamps.get(key)

    def export_state(self, metric_name: str) -> dict:
        """Export algorithm-specific state for persistence."""
        from collections import deque

        key = self.normalize_metric_name(metric_name)
        with self._lock:
            baseline = self._get_or_create_baseline(key)
            if isinstance(baseline, RollingBaseline):
                baseline_data = {
                    "type": "rolling_average",
                    "samples": baseline.get_history(),
                }
            elif isinstance(baseline, EWMABaseline):
                baseline_data = {
                    "type": "ewma",
                    "ewma": baseline._ewma,
                    "sample_count": baseline._sample_count,
                }
            else:
                baseline_data = {}

            return {
                "baseline": baseline_data,
                "warmup_candidates": list(self._warmup_candidates.get(key, [])),
            }

    def restore_state(
        self,
        metric_name: str,
        state_data: dict,
        last_timestamp: Optional[datetime] = None,
    ) -> None:
        """Restore algorithm-specific state from persisted snapshot."""
        from collections import deque

        key = self.normalize_metric_name(metric_name)
        with self._lock:
            baseline = self._get_or_create_baseline(key)
            baseline_data = state_data.get("baseline", {})
            if isinstance(baseline, RollingBaseline):
                samples = baseline_data.get("samples", [])
                baseline._samples = deque(
                    [float(s) for s in samples],
                    maxlen=baseline.window_size,
                )
            elif isinstance(baseline, EWMABaseline):
                raw_ewma = baseline_data.get("ewma")
                baseline._ewma = float(raw_ewma) if raw_ewma is not None else None
                baseline._sample_count = int(baseline_data.get("sample_count", 0))

            warmup = state_data.get("warmup_candidates", [])
            if warmup:
                self._warmup_candidates[key] = [float(c) for c in warmup]
            else:
                self._warmup_candidates.pop(key, None)

            if last_timestamp is not None:
                if last_timestamp.tzinfo is None or last_timestamp.utcoffset() is None:
                    last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
                self._last_timestamps[key] = self._normalize_timestamp(last_timestamp)
