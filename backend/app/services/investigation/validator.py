"""Validation and grounding guardrails ensuring AI investigation results adhere to authentic telemetry evidence."""

from uuid import UUID
from app.schemas.investigation import EvidencePackage, InvestigationResult


class GroundingValidationError(ValueError):
    """Raised when an investigation result violates evidence grounding constraints."""
    pass


def validate_investigation_result_against_evidence(
    result: InvestigationResult,
    evidence: EvidencePackage,
) -> None:
    """Verifies that an InvestigationResult is strictly grounded in the authentic EvidencePackage.
    
    Guarantees:
    - Every timeline event references an actual anomaly event ID in the evidence package.
    - Root-cause analysis references an existing deterministic root-cause candidate.
    - Candidate service ID matches the candidate record.
    - Every remediation action requires explicit human approval.
    - No executable command snippets are permitted.
    - Evidence citations reference valid source IDs.
    """
    valid_event_ids = {e.event_id for e in evidence.participating_events}
    valid_candidate_map = {c.candidate_id: c for c in evidence.ranked_candidates}

    # 1. Timeline event grounding
    for ev in result.timeline:
        if ev.event_id not in valid_event_ids:
            raise GroundingValidationError(
                f"Grounding violation: Timeline event references foreign or hallucinated anomaly event ID '{ev.event_id}'. "
                "All timeline events must originate from the correlation group's authentic anomaly events."
            )

    # 2. Root cause candidate grounding
    rc = result.root_cause_analysis
    if rc.candidate_id not in valid_candidate_map:
        raise GroundingValidationError(
            f"Grounding violation: Root cause explanation cites candidate ID '{rc.candidate_id}', "
            "which does not exist among the deterministic ranked candidates in this correlation group."
        )

    matched_candidate = valid_candidate_map[rc.candidate_id]
    if rc.service_id != matched_candidate.service_id:
        raise GroundingValidationError(
            f"Grounding violation: Candidate service ID mismatch for candidate '{rc.candidate_id}'. "
            f"Expected '{matched_candidate.service_id}', received '{rc.service_id}'."
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
                "Executable snippets are strictly prohibited in Sprint 5.1."
            )

    # 4. Evidence reference source validation
    all_valid_source_ids = (
        valid_event_ids
        | set(valid_candidate_map.keys())
        | {d.source_service_id for d in evidence.service_dependencies}
        | {d.target_service_id for d in evidence.service_dependencies}
        | {evidence.correlation_group_id}
    )

    for ref in result.evidence_references:
        if ref.source_id not in all_valid_source_ids:
            raise GroundingValidationError(
                f"Grounding violation: Evidence citation references foreign source ID '{ref.source_id}'. "
                "Citations must reference authentic records present in the evidence package."
            )

