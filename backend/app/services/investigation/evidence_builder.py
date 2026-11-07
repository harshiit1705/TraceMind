"""Evidence builder service assembling strictly grounded, sanitized telemetry context for incident investigation."""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.correlation import (
    CorrelationEventAssociation,
    CorrelationGroup,
    RootCauseCandidate,
)
from app.models.project import Project
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.schemas.investigation import (
    EvidenceCandidateItem,
    EvidenceDependencyItem,
    EvidenceEventItem,
    EvidencePackage,
)


# --- Secret Redaction Engine ---

# Patterns for secrets, tokens, passwords, and private keys
_SECRET_PATTERNS = [
    # Connection strings containing user:password@host
    (
        re.compile(r'(?i)\b(postgresql|postgres|mysql|redis|mongodb|amqp)://([^:]+):(.+?)@([a-zA-Z0-9_\-\.]+)(:\d+)?(/|\b)'),
        r'\1://\2:[REDACTED_PASSWORD]@\4\5\6',
    ),
    # Bearer tokens
    (re.compile(r'(?i)Bearer\s+[a-zA-Z0-9_\-\.]{15,}'), 'Bearer [REDACTED_TOKEN]'),
    # Key-value assignments (password=..., secret=..., token=..., api_key=...)
    (
        re.compile(r'(?i)\b(password|passwd|pwd|secret|api_key|apikey|auth_token|access_token|private_key)\b\s*[:=]\s*["\']?([^\s"\'`;,]+)'),
        r'\1=[REDACTED]',
    ),
    # Common API key prefix formats (Google, AWS, GitHub, OpenAI)
    (re.compile(r'\bAIza[a-zA-Z0-9_\-]{30,40}\b'), '[REDACTED_API_KEY]'),
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), '[REDACTED_AWS_KEY]'),
    (re.compile(r'\bghp_[a-zA-Z0-9]{36}\b'), '[REDACTED_GITHUB_TOKEN]'),
    (re.compile(r'\bsk-[a-zA-Z0-9]{20,}\b'), '[REDACTED_SECRET_KEY]'),
    # PEM Private Keys
    (re.compile(r'-----BEGIN [A-Z ]+ PRIVATE KEY-----[^-]+-----END [A-Z ]+ PRIVATE KEY-----'), '[REDACTED_PRIVATE_KEY]'),
]


def redact_secrets(text: Optional[str]) -> Optional[str]:
    """Sanitizes text strings by replacing sensitive credentials with redaction markers."""
    if text is None:
        return None
    scrubbed = text
    for pattern, replacement in _SECRET_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def _sanitize_dict(data: Any) -> Any:
    """Recursively scrub string values in dictionary or list structures."""
    if isinstance(data, str):
        return redact_secrets(data)
    elif isinstance(data, dict):
        return {k: _sanitize_dict(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_sanitize_dict(item) for item in data]
    return data


class EvidenceBuilder:
    """Collects, grounds, sanitizes, and deterministically hashes telemetry evidence for a CorrelationGroup."""

    def __init__(self, db: Session):
        self.db = db

    def build_evidence_package(
        self,
        correlation_group_id: UUID,
        expected_project_id: Optional[UUID] = None,
    ) -> EvidencePackage:
        """Assembles a verified, sanitized EvidencePackage from actual database records.
        
        Guarantees:
        - Strictly isolates evaluation within project boundaries.
        - Preserves authentic event IDs, timestamps, values, and rankings.
        - Zero hallucinated logs, traces, or metrics.
        - Explicitly enumerates unobserved telemetry and missing evidence.
        - Redacts credentials and secrets from untrusted text fields.
        - Computes deterministic SHA-256 evidence hash.
        """
        # 1. Fetch correlation group
        group: Optional[CorrelationGroup] = (
            self.db.query(CorrelationGroup)
            .filter(CorrelationGroup.id == correlation_group_id)
            .first()
        )
        if not group:
            raise ValueError(f"Correlation group '{correlation_group_id}' was not found.")

        # Project boundary enforcement
        if expected_project_id and group.project_id != expected_project_id:
            raise PermissionError(
                f"Project isolation violation: Correlation group '{correlation_group_id}' "
                f"belongs to project '{group.project_id}', not '{expected_project_id}'."
            )

        project = self.db.query(Project).filter(Project.id == group.project_id).first()
        proj_slug = project.slug if project else "unknown"
        proj_name = project.name if project else "Unknown Project"

        missing_evidence: List[str] = []

        # 2. Fetch associated anomaly events
        assocs: List[CorrelationEventAssociation] = (
            self.db.query(CorrelationEventAssociation)
            .filter(CorrelationEventAssociation.correlation_group_id == correlation_group_id)
            .order_by(CorrelationEventAssociation.created_at.asc())
            .all()
        )

        event_items: List[EvidenceEventItem] = []
        participating_service_ids: Set[UUID] = set()

        for a in assocs:
            ev: Optional[AnomalyEvent] = (
                self.db.query(AnomalyEvent)
                .filter(
                    AnomalyEvent.id == a.anomaly_event_id,
                    AnomalyEvent.project_id == group.project_id,
                )
                .first()
            )
            if not ev:
                missing_evidence.append(
                    f"Anomaly event '{a.anomaly_event_id}' referenced in correlation group was missing or mismatched project."
                )
                continue

            participating_service_ids.add(ev.service_id)
            svc: Optional[Service] = self.db.query(Service).filter(Service.id == ev.service_id).first()
            svc_name = svc.name if svc else "Unknown Service"
            svc_ident = svc.identifier if svc else "unknown"

            # Query baseline if available
            baseline: Optional[AnomalyBaseline] = (
                self.db.query(AnomalyBaseline)
                .filter(
                    AnomalyBaseline.project_id == group.project_id,
                    AnomalyBaseline.service_id == ev.service_id,
                    AnomalyBaseline.metric_name == ev.metric_name,
                )
                .first()
            )

            has_baseline = baseline is not None
            b_state = (baseline.baseline_state or {}) if baseline else {}
            b_mean = b_state.get("mean")
            b_std = b_state.get("std_dev")

            if not has_baseline:
                missing_evidence.append(
                    f"Missing baseline model for service '{svc_name}' on metric '{ev.metric_name}' (provisional evaluation)."
                )

            event_items.append(
                EvidenceEventItem(
                    event_id=ev.id,
                    service_id=ev.service_id,
                    service_name=redact_secrets(svc_name) or "",
                    service_identifier=redact_secrets(svc_ident) or "",
                    metric_name=redact_secrets(ev.metric_name) or "",
                    observed_value=ev.observed_value,
                    expected_baseline=ev.expected_baseline,
                    deviation_pct=ev.deviation_pct,
                    severity=ev.severity,
                    detection_method=ev.detection_method or "unknown",
                    occurred_at=ev.occurred_at,
                    relevance_score=a.relevance_score,
                    correlation_reason=redact_secrets(a.correlation_reason) or "",
                    has_persisted_baseline=has_baseline,
                    baseline_mean=b_mean,
                    baseline_std_dev=b_std,
                )
            )

        # Sort events deterministically by timestamp, then event_id
        event_items.sort(key=lambda e: (e.occurred_at, str(e.event_id)))

        # 3. Fetch service dependencies among participating services
        dep_items: List[EvidenceDependencyItem] = []
        if participating_service_ids:
            deps: List[ServiceDependency] = (
                self.db.query(ServiceDependency)
                .filter(
                    ServiceDependency.project_id == group.project_id,
                    ServiceDependency.source_service_id.in_(participating_service_ids),
                    ServiceDependency.target_service_id.in_(participating_service_ids),
                )
                .all()
            )

            services_cache = {
                s.id: s for s in self.db.query(Service).filter(Service.id.in_(participating_service_ids)).all()
            }

            for d in deps:
                src_svc = services_cache.get(d.source_service_id)
                tgt_svc = services_cache.get(d.target_service_id)
                dep_items.append(
                    EvidenceDependencyItem(
                        source_service_id=d.source_service_id,
                        source_service_name=redact_secrets(src_svc.name if src_svc else "Unknown") or "",
                        target_service_id=d.target_service_id,
                        target_service_name=redact_secrets(tgt_svc.name if tgt_svc else "Unknown") or "",
                        dependency_type=d.dependency_type,
                        description=redact_secrets(d.description),
                    )
                )

        dep_items.sort(key=lambda d: (str(d.source_service_id), str(d.target_service_id)))

        # 4. Fetch ranked root-cause candidates
        cands: List[RootCauseCandidate] = (
            self.db.query(RootCauseCandidate)
            .filter(RootCauseCandidate.correlation_group_id == correlation_group_id)
            .order_by(RootCauseCandidate.rank.asc())
            .all()
        )

        candidate_items: List[EvidenceCandidateItem] = []
        for c in cands:
            svc = self.db.query(Service).filter(Service.id == c.service_id).first()
            svc_name = svc.name if svc else "Unknown Service"
            svc_ident = svc.identifier if svc else "unknown"

            raw_reasons = c.reasons_json or {}
            sanitized_reasons = _sanitize_dict(raw_reasons)
            supporting_ev = [redact_secrets(s) or "" for s in raw_reasons.get("supporting_evidence", [])]
            limitations = [redact_secrets(l) or "" for l in raw_reasons.get("limitations", [])]

            candidate_items.append(
                EvidenceCandidateItem(
                    candidate_id=c.id,
                    service_id=c.service_id,
                    service_name=redact_secrets(svc_name) or "",
                    service_identifier=redact_secrets(svc_ident) or "",
                    rank=c.rank,
                    score=c.score,
                    confidence=c.confidence,
                    is_probable_root_cause=c.is_probable_root_cause,
                    temporal_precedence_score=c.temporal_precedence_score,
                    topological_score=c.topological_score,
                    blast_radius_score=c.blast_radius_score,
                    severity_score=c.severity_score,
                    reasons=sanitized_reasons,
                    supporting_evidence=supporting_ev,
                    limitations=limitations,
                )
            )

        # 5. Represent missing evidence and unmapped topology explicitly
        if not group.topology_complete:
            missing_evidence.append(
                "Incomplete service dependency topology: one or more participating services lack registered DAG edges."
            )

        if not event_items:
            missing_evidence.append("Correlation group contains zero valid anomaly events.")

        # Always explicitly disclose uninstrumented telemetry sources
        unobserved_telemetry = [
            "Raw application logs (e.g. Loki, Elasticsearch) are uninstrumented; no log lines exist.",
            "Distributed trace spans (e.g. OpenTelemetry, Jaeger) are uninstrumented; no trace spans exist.",
        ]

        topo_explanation = (
            "Verified DAG: All participating services have registered dependency edges in project topology."
            if group.topology_complete
            else "Incomplete Topology: Missing dependency relationships among one or more participating services."
        )

        # 6. Compute deterministic evidence hash
        canonical_dict = {
            "correlation_group_id": str(group.id),
            "project_id": str(group.project_id),
            "time_window_start": group.time_window_start.isoformat(),
            "time_window_end": group.time_window_end.isoformat(),
            "events": [
                {
                    "event_id": str(e.event_id),
                    "service_id": str(e.service_id),
                    "metric_name": e.metric_name,
                    "observed_value": e.observed_value,
                    "occurred_at": e.occurred_at.isoformat(),
                }
                for e in event_items
            ],
            "dependencies": [
                {
                    "source": str(d.source_service_id),
                    "target": str(d.target_service_id),
                    "type": d.dependency_type,
                }
                for d in dep_items
            ],
            "candidates": [
                {
                    "candidate_id": str(c.candidate_id),
                    "service_id": str(c.service_id),
                    "rank": c.rank,
                    "score": c.score,
                }
                for c in candidate_items
            ],
        }

        canonical_json = json.dumps(canonical_dict, sort_keys=True)
        evidence_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return EvidencePackage(
            package_version="1.0",
            correlation_group_id=group.id,
            project_id=group.project_id,
            project_slug=proj_slug,
            project_name=proj_name,
            time_window_start=group.time_window_start,
            time_window_end=group.time_window_end,
            confidence_score=group.confidence_score,
            topology_complete=group.topology_complete,
            topology_status_explanation=topo_explanation,
            participating_events=event_items,
            service_dependencies=dep_items,
            ranked_candidates=candidate_items,
            missing_evidence=missing_evidence,
            unobserved_telemetry=unobserved_telemetry,
            evidence_hash=evidence_hash,
        )
