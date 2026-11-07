"""Validation and grounding guardrails ensuring AI investigation results adhere to authentic telemetry evidence."""

from datetime import datetime, timezone
from typing import Dict, Set
from uuid import UUID

from app.schemas.investigation import (
    EvidenceCandidateItem,
    EvidenceEventItem,
    EvidencePackage,
    InvestigationResult,
)


class GroundingValidationError(ValueError):
    """Raised when an investigation result violates evidence grounding constraints."""
    pass


# Supported evidence source record types and their allowed fields
ALLOWED_SOURCE_RECORD_TYPES = {
    "anomaly_event",
    "service_dependency",
    "root_cause_candidate",
    "correlation_group",
    "baseline",
}

ALLOWED_FIELDS_BY_SOURCE_TYPE: Dict[str, Set[str]] = {
    "anomaly_event": {
        "observed_value",
        "expected_baseline",
        "deviation_pct",
        "severity",
        "metric_name",
        "occurred_at",
        "relevance_score",
        "baseline_mean",
        "baseline_std_dev",
        "correlation_reason",
    },
    "service_dependency": {
        "dependency_type",
        "description",
        "source_service_id",
        "target_service_id",
        "source_service_name",
        "target_service_name",
    },
    "root_cause_candidate": {
        "rank",
        "score",
        "confidence",
        "is_probable_root_cause",
        "temporal_precedence_score",
        "topological_score",
        "blast_radius_score",
        "severity_score",
        "reasons",
        "supporting_evidence",
        "limitations",
    },
    "correlation_group": {
        "confidence_score",
        "time_window_start",
        "time_window_end",
        "topology_complete",
        "topology_status_explanation",
    },
    "baseline": {
        "baseline_mean",
        "baseline_std_dev",
        "expected_baseline",
        "detection_method",
        "sample_count",
    },
}


def _normalize_datetime(dt: datetime) -> datetime:
    """Ensure datetime is UTC timezone-aware for deterministic timestamp comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_investigation_result_against_evidence(
    result: InvestigationResult,
    evidence: EvidencePackage,
) -> None:
    """Verifies that an InvestigationResult is strictly grounded in the authentic EvidencePackage.
    
    Guarantees:
    - Every timeline event references an authentic anomaly event ID.
    - Timeline event service_id, service_name, metric_name, timestamp, and severity strictly match the evidence.
    - Root-cause candidate ID, service ID, and service name match deterministic candidates.
    - Citations cite valid source types, verified source IDs, and authentic fields available on those records.
    - Every remediation action requires explicit human approval; no executable commands are permitted.
    """
    event_map: Dict[UUID, EvidenceEventItem] = {e.event_id: e for e in evidence.participating_events}
    candidate_map: Dict[UUID, EvidenceCandidateItem] = {c.candidate_id: c for c in evidence.ranked_candidates}

    # 1. Timeline event grounding: check event_id, service_id, service_name, metric_name, timestamp, severity
    for ev in result.timeline:
        if ev.event_id not in event_map:
            raise GroundingValidationError(
                f"Grounding violation: Timeline event references foreign or hallucinated anomaly event ID '{ev.event_id}'. "
                "All timeline events must originate from the correlation group's authentic anomaly events."
            )

        orig_ev = event_map[ev.event_id]

        # Verify service_id
        if ev.service_id != orig_ev.service_id:
            raise GroundingValidationError(
                f"Grounding violation: Timeline event '{ev.event_id}' has mismatched service_id. "
                f"Expected '{orig_ev.service_id}', received '{ev.service_id}'."
            )

        # Verify service_name when available
        if orig_ev.service_name and ev.service_name.strip() != orig_ev.service_name.strip():
            raise GroundingValidationError(
                f"Grounding violation: Timeline event '{ev.event_id}' has mismatched service_name. "
                f"Expected '{orig_ev.service_name}', received '{ev.service_name}'."
            )

        # Verify metric_name
        if ev.metric_name.strip() != orig_ev.metric_name.strip():
            raise GroundingValidationError(
                f"Grounding violation: Timeline event '{ev.event_id}' has mismatched metric_name. "
                f"Expected '{orig_ev.metric_name}', received '{ev.metric_name}'."
            )

        # Verify timestamp matches within sub-second precision
        ev_ts = _normalize_datetime(ev.timestamp)
        orig_ts = _normalize_datetime(orig_ev.occurred_at)
        if abs((ev_ts - orig_ts).total_seconds()) > 0.001:
            raise GroundingValidationError(
                f"Grounding violation: Timeline event '{ev.event_id}' timestamp was altered. "
                f"Expected '{orig_ev.occurred_at.isoformat()}', received '{ev.timestamp.isoformat()}'."
            )

        # Verify severity matches
        if ev.severity.strip().lower() != orig_ev.severity.strip().lower():
            raise GroundingValidationError(
                f"Grounding violation: Timeline event '{ev.event_id}' severity was altered. "
                f"Expected '{orig_ev.severity}', received '{ev.severity}'."
            )

    # 2. Root cause candidate grounding
    rc = result.root_cause_analysis
    if rc.candidate_id not in candidate_map:
        raise GroundingValidationError(
            f"Grounding violation: Root cause explanation cites candidate ID '{rc.candidate_id}', "
            "which does not exist among the deterministic ranked candidates in this correlation group."
        )

    matched_candidate = candidate_map[rc.candidate_id]
    if rc.service_id != matched_candidate.service_id:
        raise GroundingValidationError(
            f"Grounding violation: Candidate service ID mismatch for candidate '{rc.candidate_id}'. "
            f"Expected '{matched_candidate.service_id}', received '{rc.service_id}'."
        )

    if matched_candidate.service_name and rc.service_name.strip() != matched_candidate.service_name.strip():
        raise GroundingValidationError(
            f"Grounding violation: Candidate service name mismatch for candidate '{rc.candidate_id}'. "
            f"Expected '{matched_candidate.service_name}', received '{rc.service_name}'."
        )

    # 3. Remediation human approval and executable snippet guards
    for rec in result.remediation_recommendations:
        if not rec.requires_human_approval:
            raise GroundingValidationError(
                f"Safety violation: Remediation action '{rec.title}' does not require human approval. "
                "Autonomous execution is strictly prohibited."
            )
        if rec.command_snippet is not None and rec.command_snippet.strip() != "":
            raise GroundingValidationError(
                f"Safety violation: Remediation action '{rec.title}' contains executable command snippet. "
                "Executable snippets are strictly prohibited."
            )

    # 4. Evidence reference source and field validation
    dep_service_ids = {d.source_service_id for d in evidence.service_dependencies} | {
        d.target_service_id for d in evidence.service_dependencies
    }

    for ref in result.evidence_references:
        # Validate source_record_type
        if ref.source_record_type not in ALLOWED_SOURCE_RECORD_TYPES:
            raise GroundingValidationError(
                f"Grounding violation: Invalid evidence source_record_type '{ref.source_record_type}'. "
                f"Supported types are: {sorted(ALLOWED_SOURCE_RECORD_TYPES)}."
            )

        # Validate source_id against the correct evidence collection
        if ref.source_record_type == "anomaly_event":
            if ref.source_id not in event_map:
                raise GroundingValidationError(
                    f"Grounding violation: Anomaly event citation references nonexistent source ID '{ref.source_id}'."
                )
        elif ref.source_record_type == "root_cause_candidate":
            if ref.source_id not in candidate_map:
                raise GroundingValidationError(
                    f"Grounding violation: Candidate citation references nonexistent source ID '{ref.source_id}'."
                )
        elif ref.source_record_type == "service_dependency":
            if ref.source_id not in dep_service_ids and ref.source_id not in event_map:
                raise GroundingValidationError(
                    f"Grounding violation: Service dependency citation references nonexistent service ID '{ref.source_id}'."
                )
        elif ref.source_record_type == "correlation_group":
            if ref.source_id != evidence.correlation_group_id:
                raise GroundingValidationError(
                    f"Grounding violation: Correlation group citation references foreign ID '{ref.source_id}'."
                )
        elif ref.source_record_type == "baseline":
            if ref.source_id not in event_map and ref.source_id not in dep_service_ids:
                raise GroundingValidationError(
                    f"Grounding violation: Baseline citation references nonexistent ID '{ref.source_id}'."
                )

        # Validate supported_field against allowed fields on that source record type
        allowed_fields = ALLOWED_FIELDS_BY_SOURCE_TYPE.get(ref.source_record_type, set())
        if ref.supported_field not in allowed_fields:
            raise GroundingValidationError(
                f"Grounding violation: Field '{ref.supported_field}' is not supported for source record type '{ref.source_record_type}'. "
                f"Allowed fields: {sorted(allowed_fields)}."
            )
