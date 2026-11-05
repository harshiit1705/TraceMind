import math
import pytest
from app.schemas.anomaly import (
    AnomalyDetectionConfig,
    AnomalySeverity,
    DetectionMethod,
)
from app.services.anomaly.baseline import EWMABaseline, RollingBaseline
from app.services.anomaly.detector import AnomalyDetector


# 1. Normal measurements do not trigger anomaly
def test_normal_measurements_do_not_trigger_anomaly():
    config = AnomalyDetectionConfig(
        method=DetectionMethod.ROLLING_AVERAGE,
        window_size=5,
        min_samples=3,
        threshold_pct=25.0,
    )
    detector = AnomalyDetector(config)

    # Establish baseline around 100.0 ms latency
    for v in [98.0, 102.0, 100.0]:
        detector.update_baseline("latency", v)

    assert detector.get_baseline_value("latency") == 100.0

    # Test measurements within the 25% threshold (100.0 +/- 25.0)
    for normal_val in [105.0, 115.0, 124.0]:
        result = detector.evaluate("latency", normal_val)
        assert result.is_anomaly is False
        assert result.severity == AnomalySeverity.NONE
        assert result.expected_baseline == 100.0
        assert result.deviation_pct is not None
        assert result.deviation_pct < 25.0
        assert "acceptable" in result.explanation.lower()


# 2. Measurements exceeding configured threshold trigger anomaly
def test_measurements_exceeding_threshold_trigger_anomaly():
    config = AnomalyDetectionConfig(
        method=DetectionMethod.ROLLING_AVERAGE,
        window_size=5,
        min_samples=3,
        threshold_pct=25.0,
    )
    detector = AnomalyDetector(config)

    for v in [100.0, 100.0, 100.0]:
        detector.update_baseline("latency", v)

    # Moderate spike: 135.0 (+35% > 25% threshold)
    result = detector.evaluate("latency", 135.0)
    assert result.is_anomaly is True
    assert result.observed_value == 135.0
    assert result.expected_baseline == 100.0
    assert result.deviation_pct == 35.0
    assert result.severity in (AnomalySeverity.LOW, AnomalySeverity.MEDIUM)
    assert "exceeds baseline" in result.explanation.lower()

    # Severe spike: 300.0 (+200% > 25% threshold)
    result_severe = detector.evaluate("latency", 300.0)
    assert result_severe.is_anomaly is True
    assert result_severe.deviation_pct == 200.0
    assert result_severe.severity == AnomalySeverity.CRITICAL


# 3. Rolling window updates
def test_rolling_baseline_window_updates():
    window = RollingBaseline(window_size=4, min_samples=2)

    assert window.sample_count == 0
    assert window.is_ready is False
    assert window.value is None

    window.add(10.0)
    assert window.sample_count == 1
    assert window.is_ready is False

    window.add(20.0)
    assert window.sample_count == 2
    assert window.is_ready is True
    assert window.value == 15.0  # (10 + 20) / 2

    window.add(30.0)
    window.add(40.0)
    assert window.sample_count == 4
    assert window.value == 25.0  # (10 + 20 + 30 + 40) / 4 = 100 / 4

    # 5th item exceeds capacity of 4 -> 10.0 is evicted
    window.add(50.0)
    assert window.sample_count == 4
    assert window.get_history() == [20.0, 30.0, 40.0, 50.0]
    assert window.value == 35.0  # (20 + 30 + 40 + 50) / 4 = 140 / 4


# 4. EWMA calculations and recent-weight bias
def test_ewma_baseline_calculation_and_weighting():
    # alpha = 0.5: EWMA(t) = 0.5 * val + 0.5 * EWMA(t-1)
    ewma = EWMABaseline(alpha=0.5, min_samples=3)

    assert ewma.is_ready is False
    assert ewma.value is None

    # Sample 1: Initialized to first value
    val1 = ewma.add(100.0)
    assert val1 == 100.0
    assert ewma.is_ready is False

    # Sample 2: 0.5 * 120 + 0.5 * 100 = 110.0
    val2 = ewma.add(120.0)
    assert val2 == 110.0
    assert ewma.is_ready is False

    # Sample 3: 0.5 * 140 + 0.5 * 110 = 125.0 (reaches min_samples=3)
    val3 = ewma.add(140.0)
    assert val3 == 125.0
    assert ewma.is_ready is True
    assert ewma.value == 125.0

    # Verify recent measurement receives greater weight than older one:
    # An arithmetic mean of [100, 120, 140] would be 120.0, but EWMA is 125.0
    # because the most recent sample (140) pulls it higher.
    assert ewma.value > 120.0


# 5. Insufficient historical measurements safe handling
def test_insufficient_historical_measurements():
    config = AnomalyDetectionConfig(
        method=DetectionMethod.ROLLING_AVERAGE,
        window_size=10,
        min_samples=5,
        threshold_pct=30.0,
    )
    detector = AnomalyDetector(config)

    # Record only 2 samples when 5 are required
    detector.update_baseline("error_rate", 0.5)
    detector.update_baseline("error_rate", 0.7)

    assert detector.get_sample_count("error_rate") == 2
    assert detector.get_baseline_value("error_rate") is None

    # Even a massive spike must safely return is_anomaly=False with an explanation
    result = detector.evaluate("error_rate", 85.0)
    assert result.is_anomaly is False
    assert result.expected_baseline is None
    assert result.deviation_pct is None
    assert result.severity == AnomalySeverity.NONE
    assert result.sample_count == 2
    assert "insufficient" in result.explanation.lower()


# 6. Zero-baseline division-by-zero protection
def test_zero_baseline_handling():
    config = AnomalyDetectionConfig(
        method=DetectionMethod.ROLLING_AVERAGE,
        window_size=5,
        min_samples=3,
        threshold_pct=20.0,
        threshold_abs=2.0,  # Absolute tolerance of 2.0 percentage points
    )
    detector = AnomalyDetector(config)

    # Establish zero error rate baseline (e.g. 3 consecutive 0.0 readings)
    for _ in range(3):
        detector.update_baseline("error_rate", 0.0)

    assert detector.get_baseline_value("error_rate") == 0.0

    # Case A: Observed matches zero baseline
    res_zero = detector.evaluate("error_rate", 0.0)
    assert res_zero.is_anomaly is False
    assert res_zero.expected_baseline == 0.0
    assert res_zero.deviation_pct == 0.0

    # Case B: Small deviation within threshold_abs (0.8 < 2.0)
    res_small = detector.evaluate("error_rate", 0.8)
    assert res_small.is_anomaly is False
    assert res_small.expected_baseline == 0.0
    assert res_small.deviation_pct is None  # Undefined % on 0 baseline
    assert "within absolute tolerance" in res_small.explanation.lower()

    # Case C: Significant deviation exceeding threshold_abs (8.85% error surge)
    res_surge = detector.evaluate("error_rate", 8.85)
    assert res_surge.is_anomaly is True
    assert res_surge.expected_baseline == 0.0
    assert res_surge.deviation_pct is None
    assert res_surge.severity != AnomalySeverity.NONE
    assert "exceeds absolute threshold" in res_surge.explanation.lower()


# 7. Invalid inputs handling
def test_invalid_inputs_handling():
    detector = AnomalyDetector()

    # Non-finite values
    with pytest.raises(ValueError, match="finite number"):
        detector.evaluate("latency", float("nan"))

    with pytest.raises(ValueError, match="finite number"):
        detector.evaluate("latency", float("inf"))

    with pytest.raises(ValueError, match="finite number"):
        detector.update_baseline("latency", float("-inf"))

    # Negative latency domain rule
    with pytest.raises(ValueError, match="cannot be negative"):
        detector.evaluate("latency_ms", -15.0)

    # Error rate > 100% domain rule
    with pytest.raises(ValueError, match="between 0.0 and 100.0"):
        detector.evaluate("error_rate", 150.0)

    # Empty metric name
    with pytest.raises(ValueError, match="non-empty string"):
        detector.evaluate("", 42.0)

    # Invalid baseline config values
    with pytest.raises(ValueError, match="window_size must be >= 1"):
        RollingBaseline(window_size=0)

    with pytest.raises(ValueError, match="min_samples must be >= 1"):
        RollingBaseline(window_size=5, min_samples=0)

    with pytest.raises(ValueError, match="cannot exceed window_size"):
        RollingBaseline(window_size=5, min_samples=6)

    with pytest.raises(ValueError, match="alpha must be in the range"):
        EWMABaseline(alpha=0.0)

    with pytest.raises(ValueError, match="alpha must be in the range"):
        EWMABaseline(alpha=1.5)


# 8. Anti-contamination guarantee: anomalous measurement does not contaminate baseline
def test_anomalous_measurement_does_not_contaminate_baseline():
    config = AnomalyDetectionConfig(
        method=DetectionMethod.ROLLING_AVERAGE,
        window_size=5,
        min_samples=3,
        threshold_pct=20.0,
    )
    detector = AnomalyDetector(config)

    # Seed clean baseline at 100.0
    for _ in range(5):
        detector.update_baseline("request_rate", 100.0)

    assert detector.get_baseline_value("request_rate") == 100.0
    assert detector.get_sample_count("request_rate") == 5

    # 1. evaluate() alone MUST NOT mutate baseline
    result1 = detector.evaluate("request_rate", 9999.0)
    assert result1.is_anomaly is True
    assert detector.get_baseline_value("request_rate") == 100.0
    assert detector.get_sample_count("request_rate") == 5

    # 2. evaluate_and_update() with an anomaly MUST NOT mutate baseline
    result2 = detector.evaluate_and_update("request_rate", 8500.0, update_if_normal=True)
    assert result2.is_anomaly is True
    assert detector.get_baseline_value("request_rate") == 100.0
    assert detector.get_sample_count("request_rate") == 5

    # 3. evaluate_and_update() with a normal value DOES update baseline
    result3 = detector.evaluate_and_update("request_rate", 106.0, update_if_normal=True)
    assert result3.is_anomaly is False
    # Window of 5 was [100, 100, 100, 100, 100], now [100, 100, 100, 100, 106] -> mean = 506 / 5 = 101.2
    assert detector.get_baseline_value("request_rate") == 101.2
    assert detector.get_sample_count("request_rate") == 5


# 9. Bidirectional deviation testing
def test_bidirectional_request_rate_drop():
    config = AnomalyDetectionConfig(
        method=DetectionMethod.ROLLING_AVERAGE,
        window_size=5,
        min_samples=3,
        threshold_pct=30.0,
        bidirectional=True,  # Detects both surges and drops
    )
    detector = AnomalyDetector(config)

    for _ in range(4):
        detector.update_baseline("request_rate", 1000.0)

    # 50% traffic collapse: 500 RPS vs 1000 RPS baseline (-50% deviation)
    result = detector.evaluate("request_rate", 500.0)
    assert result.is_anomaly is True
    assert result.deviation_pct == -50.0
    assert result.severity != AnomalySeverity.NONE


# 10. Strictly positive thresholds enforced
def test_strictly_positive_thresholds_enforced():
    # Pydantic validation rejects <= 0.0
    with pytest.raises(Exception):
        AnomalyDetectionConfig(threshold_pct=0.0)

    with pytest.raises(Exception):
        AnomalyDetectionConfig(threshold_pct=-10.0)

    with pytest.raises(Exception):
        AnomalyDetectionConfig(threshold_abs=0.0)

    with pytest.raises(Exception):
        AnomalyDetectionConfig(threshold_abs=-1.0)


# 11. Boolean inputs strictly rejected
def test_boolean_inputs_strictly_rejected():
    detector = AnomalyDetector()

    # Reject booleans in evaluate
    with pytest.raises(ValueError, match="cannot be a boolean"):
        detector.evaluate("latency", True)

    with pytest.raises(ValueError, match="cannot be a boolean"):
        detector.evaluate("latency", False)

    # Reject booleans in update_baseline
    with pytest.raises(ValueError, match="cannot be a boolean"):
        detector.update_baseline("latency", True)

    # Reject booleans directly in baselines
    rolling = RollingBaseline(window_size=5, min_samples=2)
    with pytest.raises(ValueError, match="cannot be a boolean"):
        rolling.add(True)

    ewma = EWMABaseline(alpha=0.3, min_samples=2)
    with pytest.raises(ValueError, match="cannot be a boolean"):
        ewma.add(False)


# 12. Warmup lifecycle and status transitions
def test_warmup_status_and_lifecycle_progression():
    from app.schemas.anomaly import DetectionStatus

    config = AnomalyDetectionConfig(min_samples=3, threshold_pct=25.0)
    detector = AnomalyDetector(config)

    # Sample 1: WARMING_UP
    r1 = detector.evaluate_and_update("latency", 100.0)
    assert r1.detection_status == DetectionStatus.WARMING_UP
    assert r1.is_anomaly is False
    assert r1.sample_count == 0  # Was 0 when evaluated, updated to 1
    assert detector.get_sample_count("latency") == 1

    # Sample 2: WARMING_UP
    r2 = detector.evaluate_and_update("latency", 100.0)
    assert r2.detection_status == DetectionStatus.WARMING_UP
    assert r2.is_anomaly is False
    assert detector.get_sample_count("latency") == 2

    # Sample 3: WARMING_UP at evaluation time, completes warmup
    r3 = detector.evaluate_and_update("latency", 100.0)
    assert r3.detection_status == DetectionStatus.WARMING_UP
    assert detector.get_sample_count("latency") == 3

    # Sample 4: Detector is now READY (min_samples=3 reached). Normal measurement
    r4 = detector.evaluate_and_update("latency", 102.0)
    assert r4.detection_status == DetectionStatus.NORMAL
    assert r4.is_anomaly is False
    assert detector.get_sample_count("latency") == 4

    # Sample 5: Spike (+80% > 25%). Detected as ANOMALY and NOT added to baseline
    r5 = detector.evaluate_and_update("latency", 180.0)
    assert r5.detection_status == DetectionStatus.ANOMALY
    assert r5.is_anomaly is True
    # Sample count stays 4 because anomaly was not added
    assert detector.get_sample_count("latency") == 4




def test_warmup_median_filter_excludes_single_extreme_outlier():
    config = AnomalyDetectionConfig(min_samples=3, threshold_pct=30.0, window_size=10)
    detector = AnomalyDetector(config)

    # The outlier is deliberately in the middle so filtering cannot depend on
    # the first observation being a trusted seed.
    for value in (100.0, 10_000.0, 101.0):
        result = detector.evaluate_and_update("latency", value)
        assert result.detection_status.value == "WARMING_UP"

    # Only two median-consistent candidates remain; the next normal sample
    # completes robust initialization without admitting the 10,000 ms spike.
    detector.evaluate_and_update("latency", 102.0)
    assert detector.get_sample_count("latency") == 3
    assert detector.get_baseline_value("latency") == pytest.approx(101.0)

    result = detector.evaluate_and_update("latency", 103.0)
    assert result.detection_status.value == "NORMAL"
    assert result.expected_baseline == pytest.approx(101.0)


def test_metric_names_are_canonicalized_inside_detector():
    detector = AnomalyDetector(AnomalyDetectionConfig(min_samples=2))
    detector.evaluate_and_update(" Latency ", 100.0)
    detector.evaluate_and_update("LATENCY", 100.0)

    assert detector.get_sample_count("latency") == 2
    assert detector.get_sample_count(" LaTeNcY ") == 2
    assert detector.get_baseline_value("LATENCY") == pytest.approx(100.0)


def test_numeric_configuration_rejects_booleans():
    for field in ("window_size", "min_samples", "alpha", "threshold_pct", "threshold_abs"):
        with pytest.raises(Exception):
            AnomalyDetectionConfig(**{field: True})

    with pytest.raises(ValueError, match="window_size"):
        RollingBaseline(window_size=True, min_samples=1)
    with pytest.raises(ValueError, match="min_samples"):
        RollingBaseline(window_size=5, min_samples=True)
    with pytest.raises(ValueError, match="alpha"):
        EWMABaseline(alpha=True, min_samples=2)
    with pytest.raises(ValueError, match="min_samples"):
        EWMABaseline(alpha=0.3, min_samples=True)


def test_detector_evaluation_and_update_is_atomic_under_concurrency():
    from concurrent.futures import ThreadPoolExecutor

    detector = AnomalyDetector(
        AnomalyDetectionConfig(method=DetectionMethod.EWMA, min_samples=2)
    )
    detector.update_baseline("latency", 100.0)
    detector.update_baseline("latency", 100.0)

    def evaluate_many(_):
        return detector.evaluate_and_update("latency", 100.0)

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(evaluate_many, range(240)))

    assert all(not result.is_anomaly for result in results)
    assert detector.get_sample_count("latency") == 242
    assert detector.get_baseline_value("latency") == pytest.approx(100.0)


def test_timestamp_policy_requires_aware_strictly_increasing_event_time():
    from datetime import datetime, timezone, timedelta
    from app.services.anomaly.detector import OutOfOrderMeasurementError

    detector = AnomalyDetector(AnomalyDetectionConfig(min_samples=2))
    first = datetime(2026, 11, 5, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    result = detector.evaluate_and_update("latency", 100.0, timestamp=first)
    assert result.timestamp == datetime(2026, 11, 5, 4, 30, tzinfo=timezone.utc)

    with pytest.raises(OutOfOrderMeasurementError, match="strictly newer"):
        detector.evaluate_and_update("latency", 101.0, timestamp=first)

    with pytest.raises(OutOfOrderMeasurementError, match="strictly newer"):
        detector.evaluate_and_update(
            "latency", 101.0,
            timestamp=datetime(2026, 11, 5, 4, 29, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        detector.evaluate_and_update("latency", 101.0, timestamp=datetime(2026, 11, 5, 4, 31))

    # Rejected timestamps must not add measurements or advance baseline state.
    assert detector.get_sample_count("latency") == 1
