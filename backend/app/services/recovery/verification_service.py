"""Recovery Verification Service: Telemetry-grounded post-remediation verification engine.

Phase 5 Implementation:
- Evaluates fresh post-remediation telemetry against historical statistical baselines.
- Explicit outcome model: RECOVERED, NOT_RECOVERED, PARTIALLY_RECOVERED, INCONCLUSIVE.
- Distinguishes execution success from true service recovery.
- Never treats missing telemetry or zero traffic as proof of recovery.
- Preserves full audit history and integrates with incident lifecycle.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedActor
from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.recommendation import Recommendation
from app.models.recovery_verification import RecoveryVerification
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.models.telemetry import ApplicationLog, MetricSample, TraceSpan
from app.schemas.common import IncidentStatus
from app.schemas.recovery_verification import (
    CheckStatus,
    RecoveryOutcome,
    RecoveryVerificationRequest,
    RecoveryVerificationResponse,
    TelemetryCheckResult,
    VerificationStatus,
)
from app.services.incident_service import IncidentNotFoundError, ProjectIsolationError
from app.services.remediation.exceptions import (
    DuplicateExecutionError,
    InvalidRemediationStateError,
    RemediationNotFoundError,
)

logger = logging.getLogger("tracemind.recovery_verification")


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensures datetime is timezone-aware UTC, even across SQLite naive storage."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class RecoveryVerificationService:
    """Evaluates whether an application or microservice actually recovered after an approved remediation."""

    def __init__(self, db: Session):
        self.db = db

    def _resolve_incident_and_remediation(
        self,
        incident_id: str,
        remediation_id: UUID,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> tuple[Incident, Recommendation]:
        """Resolves incident and remediation with strict project isolation."""
        if not project_id:
            raise ProjectIsolationError("Project context is mandatory for tenant isolation.")
        if not actor.can_access_project(project_id):
            raise ProjectIsolationError(f"Actor '{actor.email}' is not authorized to access project '{project_id}'.")

        # Resolve incident
        inc_query = self.db.query(Incident)
        try:
            val_uuid = UUID(incident_id)
            incident = inc_query.filter(Incident.id == val_uuid).first()
        except (ValueError, TypeError):
            incident = inc_query.filter(Incident.incident_number == incident_id).first()

        if not incident:
            raise IncidentNotFoundError(f"Incident '{incident_id}' was not found.")

        if incident.project_id != project_id:
            raise ProjectIsolationError(f"Incident '{incident_id}' does not belong to project '{project_id}'.")

        # Resolve remediation
        rec = self.db.query(Recommendation).filter(Recommendation.id == remediation_id).first()
        if not rec:
            raise RemediationNotFoundError(f"Remediation '{remediation_id}' was not found.")

        # Ensure recommendation is linked to this incident/project
        rec_incident_id = rec.incident_id
        if not rec_incident_id and rec.investigation:
            rec_incident_id = rec.investigation.incident_id

        if rec_incident_id and rec_incident_id != incident.id:
            raise ProjectIsolationError(f"Remediation '{remediation_id}' is not linked to incident '{incident_id}'.")

        return incident, rec

    def _to_response_dto(self, v: RecoveryVerification) -> RecoveryVerificationResponse:
        """Converts ORM record to RecoveryVerificationResponse DTO."""
        raw_checks = v.checks_summary_json or []
        parsed_checks = []
        for c in raw_checks:
            try:
                parsed_checks.append(TelemetryCheckResult(**c))
            except Exception:
                pass

        suggested_status = None
        if v.recovery_outcome == RecoveryOutcome.RECOVERED.value:
            suggested_status = IncidentStatus.MITIGATED.value
        elif v.recovery_outcome == RecoveryOutcome.PARTIALLY_RECOVERED.value:
            suggested_status = IncidentStatus.INVESTIGATING.value

        return RecoveryVerificationResponse(
            id=v.id,
            incident_id=v.incident_id,
            remediation_id=v.remediation_id,
            project_id=v.project_id,
            execution_attempt_id=v.execution_attempt_id,
            target_service=v.target_service,
            status=VerificationStatus(v.status),
            recovery_outcome=RecoveryOutcome(v.recovery_outcome) if v.recovery_outcome else None,
            verification_window_start=v.verification_window_start,
            verification_window_end=v.verification_window_end,
            sample_count=v.sample_count,
            checks_summary=parsed_checks,
            evidence_snapshot=v.evidence_snapshot_json or {},
            explanation=v.explanation,
            error_message=v.error_message,
            verified_by=v.verified_by,
            suggested_incident_status=suggested_status,
            created_at=v.created_at,
            updated_at=v.updated_at,
        )

    def start_verification(
        self,
        incident_id: str,
        remediation_id: UUID,
        project_id: UUID,
        actor: AuthenticatedActor,
        req: RecoveryVerificationRequest,
    ) -> RecoveryVerificationResponse:
        """Executes telemetry-grounded recovery verification evaluating fresh post-remediation evidence."""
        if not actor.can_verify_recovery():
            raise InvalidRemediationStateError(f"Role '{actor.role.value}' is not authorized to run recovery verification.")

        incident, rec = self._resolve_incident_and_remediation(incident_id, remediation_id, project_id, actor)

        # Execution guard: Recovery verification cannot run before confirmed remediation execution
        # OUTCOME_UNKNOWN and unexecuted remediations cannot be verified as recovered
        if rec.status != "EXECUTED":
            raise InvalidRemediationStateError(
                f"Cannot verify recovery for remediation in status '{rec.status}'. Remediation must be confirmed EXECUTED first."
            )

        now = datetime.now(timezone.utc)

        # Concurrency guard: Prevent concurrent duplicate verification runs on the same remediation
        active_verification = (
            self.db.query(RecoveryVerification)
            .filter(
                RecoveryVerification.remediation_id == rec.id,
                RecoveryVerification.status == VerificationStatus.RUNNING.value,
            )
            .first()
        )
        if active_verification:
            created = ensure_utc(active_verification.created_at)
            if created and (now - created).total_seconds() < 60:
                raise DuplicateExecutionError(
                    f"A recovery verification is already actively running for remediation '{remediation_id}'."
                )

        window_duration = timedelta(seconds=req.verification_window_seconds)

        # Post-remediation window starts when execution occurred; strictly excludes pre-remediation telemetry
        window_start = ensure_utc(rec.executed_at) or (now - window_duration)
        window_end = max(now, window_start + window_duration)

        target_service_str = rec.target_service or "inventory-service"
        target_service = (
            self.db.query(Service)
            .filter(Service.project_id == project_id, Service.slug == target_service_str)
            .first()
        )
        if not target_service:
            target_service = (
                self.db.query(Service)
                .filter(Service.project_id == project_id, Service.name == target_service_str)
                .first()
            )

        verification_record = RecoveryVerification(
            id=uuid4(),
            incident_id=incident.id,
            remediation_id=rec.id,
            project_id=project_id,
            execution_attempt_id=rec.execution_attempt_id,
            target_service=target_service_str,
            status=VerificationStatus.RUNNING.value,
            verification_window_start=window_start,
            verification_window_end=window_end,
            verified_by=actor.name,
        )
        self.db.add(verification_record)
        self.db.commit()
        self.db.refresh(verification_record)

        try:
            # Step 1: Collect fresh post-remediation metric samples
            metric_query = self.db.query(MetricSample).filter(
                MetricSample.project_id == project_id,
                MetricSample.timestamp >= window_start,
                MetricSample.timestamp <= window_end,
            )
            if target_service:
                metric_query = metric_query.filter(MetricSample.service_id == target_service.id)

            metric_samples = metric_query.all()
            sample_count = len(metric_samples)
            verification_record.sample_count = sample_count

            # Step 2: Collect fresh post-remediation logs
            log_query = self.db.query(ApplicationLog).filter(
                ApplicationLog.project_id == project_id,
                ApplicationLog.timestamp >= window_start,
                ApplicationLog.timestamp <= window_end,
            )
            if target_service:
                log_query = log_query.filter(ApplicationLog.service_id == target_service.id)
            logs = log_query.all()

            # Step 3: Collect fresh post-remediation trace spans
            span_query = self.db.query(TraceSpan).filter(
                TraceSpan.project_id == project_id,
                TraceSpan.start_time >= window_start,
                TraceSpan.start_time <= window_end,
            )
            if target_service:
                span_query = span_query.filter(TraceSpan.service_id == target_service.id)
            spans = span_query.all()

            # Step 4: Retrieve historical baseline for target service
            baselines = {}
            if target_service:
                base_rows = (
                    self.db.query(AnomalyBaseline)
                    .filter(
                        AnomalyBaseline.project_id == project_id,
                        AnomalyBaseline.service_id == target_service.id,
                    )
                    .all()
                )
                baselines = {b.metric_name: b for b in base_rows}

            # Step 5: Evaluate explainable deterministic verification criteria
            checks: List[TelemetryCheckResult] = []
            error_logs = [l for l in logs if l.level in ("ERROR", "CRITICAL")]
            error_spans = [s for s in spans if s.status == "error" or (s.http_status_code and s.http_status_code >= 500)]

            # Check A: Minimum Telemetry Sample Volume
            if sample_count < req.min_sample_count:
                checks.append(
                    TelemetryCheckResult(
                        check_name="telemetry_sample_volume",
                        status=CheckStatus.INCONCLUSIVE,
                        metric_name="sample_count",
                        observed_value=sample_count,
                        baseline_expected=f">={req.min_sample_count}",
                        details=(
                            f"Insufficient telemetry samples collected ({sample_count} observed, minimum {req.min_sample_count} required). "
                            "Cannot reliably evaluate recovery on an idle or non-emitting service."
                        ),
                    )
                )
            else:
                checks.append(
                    TelemetryCheckResult(
                        check_name="telemetry_sample_volume",
                        status=CheckStatus.PASSED,
                        metric_name="sample_count",
                        observed_value=sample_count,
                        baseline_expected=f">={req.min_sample_count}",
                        details=f"Sufficient post-remediation telemetry volume collected ({sample_count} samples).",
                    )
                )

            # Check B: Latency Normalization vs Baseline
            latency_samples = [m.value for m in metric_samples if m.metric_name == "latency"]
            if latency_samples:
                mean_latency = sum(latency_samples) / len(latency_samples)
                p95_latency = sorted(latency_samples)[int(len(latency_samples) * 0.95)]
                lat_base = baselines.get("latency")

                expected_threshold = 100.0  # Safe default 100ms
                if lat_base:
                    b_state = lat_base.baseline_state or {}
                    expected_mean = b_state.get("mean")
                    if expected_mean is None and hasattr(lat_base, "expected_mean"):
                        expected_mean = getattr(lat_base, "expected_mean")
                    expected_stddev = b_state.get("stddev")
                    if expected_stddev is None and hasattr(lat_base, "expected_stddev"):
                        expected_stddev = getattr(lat_base, "expected_stddev")
                    stddev = float(expected_stddev or 15.0)

                    if expected_mean is not None:
                        expected_threshold = max(80.0, float(expected_mean) + (2.0 * stddev))

                if p95_latency <= expected_threshold:
                    checks.append(
                        TelemetryCheckResult(
                            check_name="latency_normalization",
                            status=CheckStatus.PASSED,
                            metric_name="latency",
                            observed_value=round(p95_latency, 2),
                            baseline_expected=round(expected_threshold, 2),
                            details=f"P95 latency normalized to {p95_latency:.1f}ms (threshold: {expected_threshold:.1f}ms).",
                        )
                    )
                else:
                    checks.append(
                        TelemetryCheckResult(
                            check_name="latency_normalization",
                            status=CheckStatus.FAILED,
                            metric_name="latency",
                            observed_value=round(p95_latency, 2),
                            baseline_expected=round(expected_threshold, 2),
                            details=f"P95 latency remains elevated at {p95_latency:.1f}ms (exceeds threshold {expected_threshold:.1f}ms).",
                        )
                    )
            else:
                checks.append(
                    TelemetryCheckResult(
                        check_name="latency_normalization",
                        status=CheckStatus.INCONCLUSIVE,
                        metric_name="latency",
                        details="No post-remediation latency samples found in evaluation window.",
                    )
                )

            # Check C: Error Rate Threshold
            error_rate_samples = [m.value for m in metric_samples if m.metric_name in ("error_rate", "5xx_rate")]
            if error_rate_samples:
                max_error_rate = max(error_rate_samples)
                if max_error_rate <= 1.0:
                    checks.append(
                        TelemetryCheckResult(
                            check_name="error_rate_subsided",
                            status=CheckStatus.PASSED,
                            metric_name="error_rate",
                            observed_value=round(max_error_rate, 2),
                            baseline_expected="<=1.0%",
                            details=f"Error rate dropped below threshold to {max_error_rate:.2f}%.",
                        )
                    )
                else:
                    checks.append(
                        TelemetryCheckResult(
                            check_name="error_rate_subsided",
                            status=CheckStatus.FAILED,
                            metric_name="error_rate",
                            observed_value=round(max_error_rate, 2),
                            baseline_expected="<=1.0%",
                            details=f"Error rate remains elevated at {max_error_rate:.2f}%.",
                        )
                    )
            else:
                # If no explicit error_rate metric, infer from log & span errors
                if len(error_logs) > 0:
                    checks.append(
                        TelemetryCheckResult(
                            check_name="error_rate_subsided",
                            status=CheckStatus.FAILED,
                            metric_name="error_rate",
                            observed_value=float(len(error_logs)),
                            baseline_expected="0 errors",
                            details=f"{len(error_logs)} error logs detected while evaluating error subsidence.",
                        )
                    )
                else:
                    checks.append(
                        TelemetryCheckResult(
                            check_name="error_rate_subsided",
                            status=CheckStatus.PASSED,
                            metric_name="error_rate",
                            observed_value=0.0,
                            baseline_expected="<=1.0%",
                            details="Zero error rate telemetry anomalies recorded post-remediation.",
                        )
                    )

            # Check D: Error Log Absence
            error_logs = [l for l in logs if l.level in ("ERROR", "CRITICAL")]
            if len(error_logs) == 0:
                checks.append(
                    TelemetryCheckResult(
                        check_name="error_logs_cleared",
                        status=CheckStatus.PASSED,
                        metric_name="error_log_count",
                        observed_value=0,
                        baseline_expected="0",
                        details="Zero ERROR or CRITICAL application logs recorded post-remediation.",
                    )
                )
            else:
                checks.append(
                    TelemetryCheckResult(
                        check_name="error_logs_cleared",
                        status=CheckStatus.FAILED,
                        metric_name="error_log_count",
                        observed_value=len(error_logs),
                        baseline_expected="0",
                        details=f"{len(error_logs)} ERROR/CRITICAL logs persisted post-remediation. Sample message: '{error_logs[0].message[:80]}'",
                    )
                )

            # Check E: Trace Span Fault Rate
            error_spans = [s for s in spans if s.status == "error" or (s.http_status_code and s.http_status_code >= 500)]
            if len(error_spans) == 0:
                checks.append(
                    TelemetryCheckResult(
                        check_name="trace_error_spans_cleared",
                        status=CheckStatus.PASSED,
                        metric_name="error_span_count",
                        observed_value=0,
                        baseline_expected="0",
                        details="Zero distributed trace error spans observed post-remediation.",
                    )
                )
            else:
                checks.append(
                    TelemetryCheckResult(
                        check_name="trace_error_spans_cleared",
                        status=CheckStatus.FAILED,
                        metric_name="error_span_count",
                        observed_value=len(error_spans),
                        baseline_expected="0",
                        details=f"{len(error_spans)} trace spans failed with 5xx/error status post-remediation.",
                    )
                )

            # Check F: Downstream Dependency Health
            if target_service:
                deps = (
                    self.db.query(ServiceDependency)
                    .filter(
                        ServiceDependency.project_id == project_id,
                        ServiceDependency.source_service_id == target_service.id,
                    )
                    .all()
                )
                downstream_ids = [d.target_service_id for d in deps]
                if downstream_ids:
                    downstream_anomalies = (
                        self.db.query(AnomalyEvent)
                        .filter(
                            AnomalyEvent.project_id == project_id,
                            AnomalyEvent.service_id.in_(downstream_ids),
                            AnomalyEvent.status == "open",
                            AnomalyEvent.occurred_at >= window_start,
                        )
                        .count()
                    )
                    if downstream_anomalies == 0:
                        checks.append(
                            TelemetryCheckResult(
                                check_name="downstream_dependencies_healthy",
                                status=CheckStatus.PASSED,
                                observed_value=0,
                                baseline_expected="0 open anomalies",
                                details="All downstream dependent microservices report healthy telemetry.",
                            )
                        )
                    else:
                        checks.append(
                            TelemetryCheckResult(
                                check_name="downstream_dependencies_healthy",
                                status=CheckStatus.FAILED,
                                observed_value=downstream_anomalies,
                                baseline_expected="0 open anomalies",
                                details=f"{downstream_anomalies} open anomalies remain active on downstream dependencies.",
                            )
                        )

            # Check G: Telemetry Freshness (Stale Telemetry Guard)
            sample_timestamps = [ensure_utc(m.timestamp) for m in metric_samples]
            latest_sample_time = max(sample_timestamps) if sample_timestamps else None
            is_stale = False
            if latest_sample_time and (now - latest_sample_time).total_seconds() > max(300, req.verification_window_seconds * 2):
                is_stale = True
                checks.append(
                    TelemetryCheckResult(
                        check_name="telemetry_freshness",
                        status=CheckStatus.INCONCLUSIVE,
                        observed_value=round((now - latest_sample_time).total_seconds(), 1),
                        baseline_expected="<300s age",
                        details=f"Post-remediation telemetry is stale. Latest sample age is {round((now - latest_sample_time).total_seconds(), 1)}s.",
                    )
                )

            # Step 6: Synthesize Overall Recovery Outcome
            operational_checks = [c for c in checks if c.check_name not in ("telemetry_sample_volume", "telemetry_freshness")]
            op_failed = [c for c in operational_checks if c.status == CheckStatus.FAILED]
            op_passed = [c for c in operational_checks if c.status == CheckStatus.PASSED]
            passed_count = len(op_passed)
            failed_count = len(op_failed)
            has_inconclusive = any(c.status == CheckStatus.INCONCLUSIVE for c in checks)

            is_simulated = rec.execution_mode == "SIMULATED"
            evidence_snapshot = {
                "target_service": target_service_str,
                "remediation_id": str(rec.id),
                "execution_mode": rec.execution_mode,
                "is_simulated_execution": is_simulated,
                "evaluation_window_seconds": req.verification_window_seconds,
                "sample_count": sample_count,
                "error_log_count": len(error_logs),
                "error_span_count": len(error_spans),
                "latency_p95_ms": round(p95_latency, 2) if latency_samples else None,
            }
            # Cryptographic SHA-256 evidence integrity hash
            raw_hash_data = json.dumps(evidence_snapshot, sort_keys=True, default=str)
            evidence_snapshot["evidence_hash"] = hashlib.sha256(raw_hash_data.encode("utf-8")).hexdigest()

            if is_stale:
                outcome = RecoveryOutcome.INCONCLUSIVE
                explanation = (
                    f"Recovery outcome is INCONCLUSIVE for service '{target_service_str}'. "
                    f"Telemetry stream is STALE (latest sample recorded {round((now - latest_sample_time).total_seconds(), 1)}s ago). "
                    "Cannot confirm recovery on inactive or stale metrics."
                )
            elif has_inconclusive or sample_count < req.min_sample_count:
                outcome = RecoveryOutcome.INCONCLUSIVE
                explanation = (
                    f"Recovery outcome is INCONCLUSIVE for service '{target_service_str}'. "
                    f"Telemetry sample volume was insufficient ({sample_count} observed, minimum {req.min_sample_count} required) "
                    "or no live traffic was detected in the post-remediation evaluation window."
                )
            elif len(op_failed) == 0:
                outcome = RecoveryOutcome.RECOVERED
                if is_simulated:
                    explanation = (
                        f"Service '{target_service_str}' recovery criteria PASSED (SIMULATED REMEDIATION - Emulated in local sandbox environment). "
                        f"All {len(op_passed)} telemetry checks passed: latency normalized to historical baseline, "
                        "zero error rate, zero error logs, and clean distributed traces confirmed."
                    )
                else:
                    explanation = (
                        f"Service '{target_service_str}' has fully RECOVERED. "
                        f"All {len(op_passed)} telemetry checks passed: latency normalized to historical baseline, "
                        "zero error rate, zero error logs, and clean distributed traces confirmed."
                    )
            else:
                lat_check = next((c for c in operational_checks if c.check_name == "latency_normalization"), None)
                err_log_check = next((c for c in operational_checks if c.check_name == "error_logs_cleared"), None)
                err_rate_check = next((c for c in operational_checks if c.check_name == "error_rate_subsided"), None)

                lat_failed = lat_check and lat_check.status == CheckStatus.FAILED
                errors_persist = (err_log_check and err_log_check.status == CheckStatus.FAILED) or (
                    err_rate_check and err_rate_check.status == CheckStatus.FAILED
                )

                if (lat_failed and errors_persist) or (len(op_passed) == 0):
                    outcome = RecoveryOutcome.NOT_RECOVERED
                    explanation = (
                        f"Service '{target_service_str}' is NOT_RECOVERED. "
                        f"Telemetry checks failed ({len(op_failed)} failures): elevated latency and active error rates/logs persist despite remediation execution."
                    )
                else:
                    outcome = RecoveryOutcome.PARTIALLY_RECOVERED
                    explanation = (
                        f"Service '{target_service_str}' is PARTIALLY_RECOVERED ({passed_count} checks passed, {failed_count} checks failed). "
                        "Some operational signals improved but error logs or downstream dependencies remain impaired."
                    )

            # Step 7: Persist verification record
            verification_record.status = VerificationStatus.COMPLETED.value
            verification_record.recovery_outcome = outcome.value
            verification_record.checks_summary_json = [c.model_dump(mode="json") for c in checks]
            verification_record.evidence_snapshot_json = evidence_snapshot
            verification_record.explanation = explanation
            verification_record.error_message = None

            # Step 8: Update incident lifecycle and audit timeline
            event_title = f"Recovery Verification: {outcome.value}"
            self._record_audit_event(
                incident=incident,
                event_type="action",
                actor=actor,
                title=event_title,
                description=explanation,
                payload={
                    "verification_id": str(verification_record.id),
                    "remediation_id": str(rec.id),
                    "outcome": outcome.value,
                    "passed_checks": passed_count,
                    "failed_checks": failed_count,
                },
            )

            # If service fully recovered, advance incident status safely
            if outcome == RecoveryOutcome.RECOVERED and incident.status in (
                IncidentStatus.INVESTIGATING.value,
                IncidentStatus.ACKNOWLEDGED.value,
            ):
                incident.status = IncidentStatus.MITIGATED.value
                self._record_audit_event(
                    incident=incident,
                    event_type="action",
                    actor=actor,
                    title="Incident Status Advanced to MITIGATED",
                    description=f"Incident status updated to MITIGATED following telemetry-verified recovery of '{target_service_str}'.",
                    payload={"recovery_outcome": outcome.value},
                )

            self.db.commit()
            self.db.refresh(verification_record)
            return self._to_response_dto(verification_record)

        except Exception as exc:
            logger.exception("Recovery verification process failed: %s", exc)
            self.db.rollback()
            v_fail = self.db.query(RecoveryVerification).filter(RecoveryVerification.id == verification_record.id).first()
            if v_fail:
                v_fail.status = VerificationStatus.FAILED.value
                v_fail.error_message = str(exc)
                self.db.commit()
                self.db.refresh(v_fail)
                return self._to_response_dto(v_fail)
            raise

    def get_verification(
        self,
        verification_id: UUID,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> RecoveryVerificationResponse:
        """Retrieves an existing recovery verification record enforcing tenant boundaries."""
        if not project_id or not actor.can_access_project(project_id):
            raise ProjectIsolationError("Unauthorized project access.")

        v = (
            self.db.query(RecoveryVerification)
            .filter(RecoveryVerification.id == verification_id, RecoveryVerification.project_id == project_id)
            .first()
        )
        if not v:
            raise RemediationNotFoundError(f"Recovery verification '{verification_id}' not found.")
        return self._to_response_dto(v)

    def list_verifications_for_incident(
        self,
        incident_id: str,
        project_id: UUID,
        actor: AuthenticatedActor,
    ) -> List[RecoveryVerificationResponse]:
        """Lists historical recovery verification records for an incident."""
        if not project_id or not actor.can_access_project(project_id):
            raise ProjectIsolationError("Unauthorized project access.")

        inc_query = self.db.query(Incident)
        try:
            val_uuid = UUID(incident_id)
            incident = inc_query.filter(Incident.id == val_uuid).first()
        except (ValueError, TypeError):
            incident = inc_query.filter(Incident.incident_number == incident_id).first()

        if not incident or incident.project_id != project_id:
            raise IncidentNotFoundError(f"Incident '{incident_id}' not found.")

        rows = (
            self.db.query(RecoveryVerification)
            .filter(RecoveryVerification.incident_id == incident.id, RecoveryVerification.project_id == project_id)
            .order_by(RecoveryVerification.created_at.desc())
            .all()
        )
        return [self._to_response_dto(r) for r in rows]

    def retry_verification(
        self,
        verification_id: UUID,
        project_id: UUID,
        actor: AuthenticatedActor,
        req: RecoveryVerificationRequest,
    ) -> RecoveryVerificationResponse:
        """Retries a previous recovery verification using fresh telemetry."""
        v = (
            self.db.query(RecoveryVerification)
            .filter(RecoveryVerification.id == verification_id, RecoveryVerification.project_id == project_id)
            .first()
        )
        if not v:
            raise RemediationNotFoundError(f"Recovery verification '{verification_id}' not found.")

        incident = self.db.query(Incident).filter(Incident.id == v.incident_id).first()
        if not incident:
            raise IncidentNotFoundError("Linked incident not found.")

        return self.start_verification(
            incident_id=str(incident.id),
            remediation_id=v.remediation_id,
            project_id=project_id,
            actor=actor,
            req=req,
        )

    def _record_audit_event(
        self,
        incident: Incident,
        event_type: str,
        actor: AuthenticatedActor,
        title: str,
        description: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> IncidentEvent:
        audit_payload = payload or {}
        audit_payload.update({
            "actor_id": actor.actor_id,
            "actor_email": actor.email,
            "actor_role": actor.role.value,
        })
        event = IncidentEvent(
            incident_id=incident.id,
            timestamp=datetime.now(timezone.utc),
            title=title,
            event_type=event_type,
            source=f"{actor.name} ({actor.role.value})",
            description=description,
            payload=audit_payload,
        )
        self.db.add(event)
        return event

    @staticmethod
    def verify_evidence_hash(evidence_snapshot: Dict[str, Any]) -> bool:
        """Verifies cryptographic SHA-256 integrity of an evidence snapshot."""
        stored_hash = evidence_snapshot.get("evidence_hash")
        if not stored_hash:
            return False
        clean_snapshot = {k: v for k, v in evidence_snapshot.items() if k != "evidence_hash"}
        raw_hash_data = json.dumps(clean_snapshot, sort_keys=True, default=str)
        calculated = hashlib.sha256(raw_hash_data.encode("utf-8")).hexdigest()
        return calculated == stored_hash
