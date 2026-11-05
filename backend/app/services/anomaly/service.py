"""Application service coordinating service-scoped anomaly evaluation.

Maintains strict project and service boundary validation, PostgreSQL persistence,
concurrency control, and anti-contamination guarantees.
"""

from typing import Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.repositories.anomaly_repository import (
    AnomalyBaselineRepository,
    AnomalyEventRepository,
)
from app.repositories.service_repository import ServiceRepository
from app.schemas.anomaly import (
    AnomalyDetectionConfig,
    AnomalyEventStatus,
    AnomalyEvaluationRequest,
    AnomalyEvaluationResponse,
    AnomalySeverity,
    DetectionMethod,
    DetectionStatus,
)
from app.services.anomaly.detector import AnomalyDetector
from app.services.anomaly.registry import AnomalyBaselineRegistry, get_anomaly_registry


class ServiceNotFoundError(Exception):
    """Raised when a service cannot be resolved within the given project."""
    pass


class AnomalyService:
    """Application service for evaluating telemetry measurements and managing baseline persistence."""

    def __init__(
        self,
        db: Session,
        registry: Optional[AnomalyBaselineRegistry] = None,
    ):
        self.db = db
        self.service_repo = ServiceRepository(db)
        self.baseline_repo = AnomalyBaselineRepository(db)
        self.event_repo = AnomalyEventRepository(db)
        self.registry = registry or get_anomaly_registry()

    def evaluate_measurement(
        self,
        request: AnomalyEvaluationRequest,
        config: Optional[AnomalyDetectionConfig] = None,
    ) -> AnomalyEvaluationResponse:
        """Resolve service within project, evaluate measurement, and transactionally persist updates.

        Raises:
            ServiceNotFoundError: If the service is not found in the given project.
            OutOfOrderMeasurementError: If timestamp is not strictly newer than the watermark.
            ValueError: If input validation fails on the metric or value.
        """
        # 1. Project-scoped service resolution
        service = self.service_repo.get_by_project_and_identifier(
            project_id=request.project_id,
            identifier=request.service_identifier,
        )
        if not service:
            raise ServiceNotFoundError(
                f"Service '{request.service_identifier}' was not found in project '{request.project_id}'."
            )

        canonical_metric = AnomalyDetector.normalize_metric_name(request.metric_name)

        # 2. Concurrency: acquire transaction-level advisory lock first (PostgreSQL)
        # Prevents race conditions on first-time baseline creation.
        self.baseline_repo.acquire_advisory_lock(
            project_id=request.project_id,
            service_id=service.id,
            metric_name=canonical_metric,
        )

        # Re-query baseline with row-level lock where supported
        baseline_row = self.baseline_repo.get(
            project_id=request.project_id,
            service_id=service.id,
            metric_name=canonical_metric,
            for_update=True,
        )

        # 3. Retrieve or restore service-scoped detector
        detector = self.registry.get(
            request.project_id,
            service.identifier,
            canonical_metric,
        )
        if detector is None:
            # Cache miss: restore detector from PostgreSQL if baseline exists
            if baseline_row is not None:
                det_config = config
                if det_config is None and baseline_row.config_snapshot:
                    det_config = AnomalyDetectionConfig(**baseline_row.config_snapshot)
                detector = AnomalyDetector(config=det_config)
                detector.restore_state(
                    canonical_metric,
                    baseline_row.baseline_state,
                    last_timestamp=baseline_row.last_event_timestamp,
                )
                detector._persisted_version = baseline_row.version
            else:
                detector = AnomalyDetector(config=config)
                detector._persisted_version = 0

            with self.registry._lock:
                key = self.registry._normalize_key(
                    request.project_id,
                    service.identifier,
                    canonical_metric,
                )
                self.registry._detectors[key] = detector
        else:
            # In-memory detector exists: synchronize if DB has newer persisted version
            if baseline_row is not None and getattr(detector, "_persisted_version", 0) < baseline_row.version:
                detector.restore_state(
                    canonical_metric,
                    baseline_row.baseline_state,
                    last_timestamp=baseline_row.last_event_timestamp,
                )
                detector._persisted_version = baseline_row.version

        # 4. Check idempotency for source_event_id if supplied
        source_event_id = getattr(request, "source_event_id", None)
        if source_event_id:
            existing_event = self.event_repo.get_by_source_event_id(
                request.project_id,
                service.id,
                canonical_metric,
                source_event_id,
            )
            if existing_event:
                return AnomalyEvaluationResponse(
                    is_anomaly=True,
                    detection_status=DetectionStatus.ANOMALY,
                    service_identifier=service.identifier,
                    metric_name=canonical_metric,
                    observed_value=existing_event.observed_value,
                    expected_baseline=existing_event.expected_baseline,
                    deviation_pct=existing_event.deviation_pct,
                    severity=AnomalySeverity(existing_event.severity),
                    detection_method=DetectionMethod(existing_event.detection_method),
                    sample_count=baseline_row.sample_count if baseline_row else 0,
                    explanation=existing_event.explanation or f"Duplicate anomaly event for source_event_id '{source_event_id}'.",
                    timestamp=existing_event.occurred_at,
                )

        # 5. Evaluate measurement against detector
        result = detector.evaluate_and_update(
            metric_name=canonical_metric,
            observed_value=request.observed_value,
            update_if_normal=True,
            timestamp=request.timestamp,
        )

        # 6. Transactional persistence
        try:
            if result.is_anomaly:
                # 6A. Persist confirmed anomaly event
                event_record = AnomalyEvent(
                    project_id=request.project_id,
                    service_id=service.id,
                    metric_name=canonical_metric,
                    observed_value=result.observed_value,
                    expected_baseline=result.expected_baseline,
                    deviation_pct=result.deviation_pct,
                    severity=result.severity.value,
                    detection_method=result.detection_method.value,
                    occurred_at=result.timestamp,
                    status=AnomalyEventStatus.OPEN.value,
                    source_event_id=source_event_id,
                    explanation=result.explanation,
                )
                self.event_repo.create(event_record)

                # 6B. Update watermark on baseline row without adding anomalous sample or incrementing sample_count
                if baseline_row is not None:
                    baseline_row.last_event_timestamp = result.timestamp
                    baseline_row.version += 1
                    self.baseline_repo.update(baseline_row)
                else:
                    baseline_row = AnomalyBaseline(
                        project_id=request.project_id,
                        service_id=service.id,
                        metric_name=canonical_metric,
                        detection_method=detector.config.method.value,
                        config_snapshot=detector.config.model_dump(),
                        baseline_state=detector.export_state(canonical_metric),
                        sample_count=detector.get_sample_count(canonical_metric),
                        last_event_timestamp=result.timestamp,
                        version=1,
                    )
                    self.baseline_repo.create(baseline_row)
            else:
                # Normal or warmup: persist updated baseline state and increment sample count
                if baseline_row is not None:
                    baseline_row.baseline_state = detector.export_state(canonical_metric)
                    baseline_row.sample_count = detector.get_sample_count(canonical_metric)
                    baseline_row.last_event_timestamp = result.timestamp
                    baseline_row.version += 1
                    self.baseline_repo.update(baseline_row)
                else:
                    baseline_row = AnomalyBaseline(
                        project_id=request.project_id,
                        service_id=service.id,
                        metric_name=canonical_metric,
                        detection_method=detector.config.method.value,
                        config_snapshot=detector.config.model_dump(),
                        baseline_state=detector.export_state(canonical_metric),
                        sample_count=detector.get_sample_count(canonical_metric),
                        last_event_timestamp=result.timestamp,
                        version=1,
                    )
                    self.baseline_repo.create(baseline_row)

            self.db.commit()
            if baseline_row is not None:
                detector._persisted_version = baseline_row.version
        except IntegrityError:
            self.db.rollback()
            self.registry.reset(request.project_id, service.identifier, canonical_metric)
            # Check if this was a concurrent duplicate source_event_id submission
            if source_event_id:
                existing_event = self.event_repo.get_by_source_event_id(
                    request.project_id,
                    service.id,
                    canonical_metric,
                    source_event_id,
                )
                if existing_event:
                    return AnomalyEvaluationResponse(
                        is_anomaly=True,
                        detection_status=DetectionStatus.ANOMALY,
                        service_identifier=service.identifier,
                        metric_name=canonical_metric,
                        observed_value=existing_event.observed_value,
                        expected_baseline=existing_event.expected_baseline,
                        deviation_pct=existing_event.deviation_pct,
                        severity=AnomalySeverity(existing_event.severity),
                        detection_method=DetectionMethod(existing_event.detection_method),
                        sample_count=baseline_row.sample_count if baseline_row else 0,
                        explanation=existing_event.explanation or f"Duplicate anomaly event for source_event_id '{source_event_id}'.",
                        timestamp=existing_event.occurred_at,
                    )
            raise
        except Exception:
            self.db.rollback()
            # Evict in-memory detector from registry so failed transaction never leaves
            # in-memory state inconsistent with the committed database state.
            self.registry.reset(request.project_id, service.identifier, canonical_metric)
            raise

        return AnomalyEvaluationResponse(
            is_anomaly=result.is_anomaly,
            detection_status=result.detection_status,
            service_identifier=service.identifier,
            metric_name=result.metric_name,
            observed_value=result.observed_value,
            expected_baseline=result.expected_baseline,
            deviation_pct=result.deviation_pct,
            severity=result.severity,
            detection_method=result.detection_method,
            sample_count=result.sample_count,
            explanation=result.explanation,
            timestamp=result.timestamp,
        )
