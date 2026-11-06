"""Deterministic, evidence-based root-cause ranking algorithm."""

from datetime import datetime
from typing import Dict, List, Optional, Set
from uuid import UUID
from app.models.anomaly import AnomalyEvent
from app.models.service import Service
from app.schemas.correlation import (
    RankingConfidence,
    RankingDimensionScore,
    RootCauseCandidateResponse,
    RootCauseRankingBreakdown,
)


class RootCauseRanker:
    """Evaluates causal evidence across temporal, topological, blast-radius, and severity dimensions.
    
    Deterministic scoring formula:
    - Temporal Precedence (weight = 0.35): Earliest anomaly receives highest score.
    - Topological Upstream Position (weight = 0.35): Services upstream of other failing nodes score higher.
    - Blast Radius (weight = 0.15): Fraction of affected downstream services reachable from candidate.
    - Severity & Metric Deviation (weight = 0.15): Anomaly severity level and % deviation magnitude.
    
    Tie-breaking policy (strictly deterministic):
    Sort candidates by:
    1. Score descending (-score)
    2. Earliest timestamp ascending (occurred_at asc)
    3. Service identifier lexicographical (service_identifier asc)
    4. Service UUID string lexicographical (service_id asc)
    """

    WEIGHT_TEMPORAL = 0.35
    WEIGHT_TOPOLOGY = 0.35
    WEIGHT_BLAST_RADIUS = 0.15
    WEIGHT_SEVERITY = 0.15

    SEVERITY_FACTORS = {
        "critical": 1.0,
        "high": 0.75,
        "medium": 0.50,
        "low": 0.25,
    }

    CAUSATION_DISCLAIMER = (
        "Probable root-cause candidate inferred from temporal precedence and topological upstream position. "
        "Telemetry correlation does not constitute proven physical causation; verify host health and logs."
    )

    @classmethod
    def rank_candidates(
        cls,
        participating_services: Dict[UUID, Service],
        events_by_service: Dict[UUID, List[AnomalyEvent]],
        upstream_map: Dict[UUID, Set[UUID]],     # service -> set of services it calls (callees / upstream)
        downstream_map: Dict[UUID, Set[UUID]],   # service -> set of services that call it (callers / downstream)
        topology_edges_exist: bool,
    ) -> List[RootCauseCandidateResponse]:
        """Rank services participating in an anomaly correlation group.
        
        Args:
            participating_services: Map of service_id to Service model.
            events_by_service: Map of service_id to list of participating AnomalyEvent records.
            upstream_map: Directed dependency graph mapping service_id to upstream dependencies it calls.
            downstream_map: Directed dependency graph mapping service_id to downstream callers that call it.
            topology_edges_exist: True if project has registered dependency edges among participating services.
        """
        service_ids = list(participating_services.keys())
        if not service_ids:
            return []

        # 1. Global group time boundaries
        all_timestamps: List[datetime] = []
        for evs in events_by_service.values():
            all_timestamps.extend([e.occurred_at for e in evs])

        min_time = min(all_timestamps)
        max_time = max(all_timestamps)
        time_span_seconds = (max_time - min_time).total_seconds()

        candidates: List[dict] = []

        for svc_id in service_ids:
            svc = participating_services[svc_id]
            svc_events = events_by_service.get(svc_id, [])
            if not svc_events:
                continue

            earliest_event = min(svc_events, key=lambda e: e.occurred_at)
            t_svc = earliest_event.occurred_at
            delta_from_first_sec = (t_svc - min_time).total_seconds()

            # --- Dimension 1: Temporal Precedence ---
            if time_span_seconds > 0:
                s_temporal = max(0.0, min(1.0, 1.0 - (delta_from_first_sec / time_span_seconds)))
                t_reason = (
                    f"First anomalous event occurred at {t_svc.strftime('%H:%M:%S UTC')} "
                    f"(+{delta_from_first_sec:.1f}s after group start)."
                )
            else:
                s_temporal = 1.0
                t_reason = f"All events in correlation group occurred simultaneously at {t_svc.strftime('%H:%M:%S UTC')}."

            # --- Dimension 2: Topological Position ---
            # Examine relationships strictly within the set of failing services in the group
            other_services = set(service_ids) - {svc_id}
            reachable_downstream_in_group = (downstream_map.get(svc_id, set())) & set(service_ids)
            reachable_upstream_in_group = (upstream_map.get(svc_id, set())) & set(service_ids)

            d_count = len(reachable_downstream_in_group)
            u_count = len(reachable_upstream_in_group)

            if len(service_ids) == 1:
                s_topology = 1.0
                topo_reason = "Sole affected service in correlation group; self-contained anomaly."
            elif not topology_edges_exist:
                s_topology = 0.40
                topo_reason = (
                    "No dependency relationships registered between participating services in project topology "
                    "(insufficient topology evidence)."
                )
            elif d_count > 0 and u_count == 0:
                s_topology = 1.0
                topo_reason = (
                    f"Upstream provider for {d_count} other failing service(s) in group; "
                    "depends on 0 failing upstream services."
                )
            elif d_count > 0 and u_count > 0:
                s_topology = 0.50 + 0.50 * (d_count / max(1, len(other_services)))
                topo_reason = (
                    f"Intermediate node in failure cascade: upstream of {d_count} failing service(s), "
                    f"but depends on {u_count} failing upstream service(s)."
                )
            elif d_count == 0 and u_count > 0:
                s_topology = 0.10
                topo_reason = (
                    f"Downstream caller service: depends on {u_count} failing upstream service(s) "
                    "and explains 0 other failing nodes."
                )
            else:
                s_topology = 0.30
                topo_reason = "No direct dependency edges between this service and other failing nodes in group."

            # --- Dimension 3: Blast Radius ---
            if len(service_ids) == 1:
                s_blast = 0.0
                blast_reason = "Isolated failure; no downstream cascade to other services."
            elif other_services and topology_edges_exist:
                s_blast = d_count / len(other_services)
                blast_reason = (
                    f"Explains {d_count} of {len(other_services)} ({s_blast * 100:.1f}%) "
                    "other affected services in group."
                )
            else:
                s_blast = 0.0
                blast_reason = (
                    "Zero downstream blast radius explainable by topology "
                    if topology_edges_exist else "Blast radius unquantifiable due to missing topology edges."
                )

            # --- Dimension 4: Severity & Metric Deviation ---
            # Max severity across service's events in this group
            max_sev = "low"
            sev_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            for e in svc_events:
                if sev_rank.get(e.severity.lower(), 1) > sev_rank.get(max_sev, 1):
                    max_sev = e.severity.lower()

            sev_factor = cls.SEVERITY_FACTORS.get(max_sev, 0.50)

            # Max absolute deviation
            max_dev = max(
                (abs(e.deviation_pct) if e.deviation_pct is not None else 0.0)
                for e in svc_events
            )
            dev_factor = min(1.0, max_dev / 200.0)
            s_severity = 0.60 * sev_factor + 0.40 * dev_factor
            sev_reason = (
                f"Peak severity is {max_sev.upper()} with peak metric deviation of +{max_dev:.1f}%."
            )

            # Composite Score Calculation
            composite_score = round(
                cls.WEIGHT_TEMPORAL * s_temporal
                + cls.WEIGHT_TOPOLOGY * s_topology
                + cls.WEIGHT_BLAST_RADIUS * s_blast
                + cls.WEIGHT_SEVERITY * s_severity,
                4,
            )

            # Confidence Determination
            if len(service_ids) == 1:
                confidence = RankingConfidence.MEDIUM
            elif not topology_edges_exist:
                confidence = RankingConfidence.LOW
            elif composite_score >= 0.70 and d_count > 0:
                confidence = RankingConfidence.HIGH
            elif composite_score >= 0.45:
                confidence = RankingConfidence.MEDIUM
            else:
                confidence = RankingConfidence.LOW

            # Supporting Evidence and Limitations
            evidence_items: List[str] = [
                f"First anomaly observed at {t_svc.strftime('%H:%M:%S UTC')} on metric '{earliest_event.metric_name}' (value: {earliest_event.observed_value:.1f}).",
                f"Total {len(svc_events)} anomaly events registered for service in this time window.",
            ]
            if d_count > 0:
                downstream_names = [
                    participating_services[cid].name
                    for cid in reachable_downstream_in_group
                    if cid in participating_services
                ]
                evidence_items.append(
                    f"Direct/transitive upstream dependency for: {', '.join(downstream_names)}."
                )

            limitations: List[str] = [cls.CAUSATION_DISCLAIMER]
            if len(service_ids) == 1:
                limitations.append(
                    "Single affected service; root cause candidate is self-contained with no observed downstream propagation."
                )
            elif not topology_edges_exist:
                limitations.append(
                    "Service dependency graph has no registered edges between these services; ranking relies primarily on temporal ordering."
                )

            breakdown = RootCauseRankingBreakdown(
                temporal_precedence=RankingDimensionScore(
                    score=round(s_temporal, 4),
                    weight=cls.WEIGHT_TEMPORAL,
                    weighted_score=round(cls.WEIGHT_TEMPORAL * s_temporal, 4),
                    reason=t_reason,
                ),
                topological_position=RankingDimensionScore(
                    score=round(s_topology, 4),
                    weight=cls.WEIGHT_TOPOLOGY,
                    weighted_score=round(cls.WEIGHT_TOPOLOGY * s_topology, 4),
                    reason=topo_reason,
                ),
                blast_radius=RankingDimensionScore(
                    score=round(s_blast, 4),
                    weight=cls.WEIGHT_BLAST_RADIUS,
                    weighted_score=round(cls.WEIGHT_BLAST_RADIUS * s_blast, 4),
                    reason=blast_reason,
                ),
                severity_magnitude=RankingDimensionScore(
                    score=round(s_severity, 4),
                    weight=cls.WEIGHT_SEVERITY,
                    weighted_score=round(cls.WEIGHT_SEVERITY * s_severity, 4),
                    reason=sev_reason,
                ),
            )

            candidates.append({
                "service_id": svc.id,
                "service_slug": svc.slug,
                "service_name": svc.name,
                "service_identifier": svc.identifier,
                "score": composite_score,
                "confidence": confidence,
                "breakdown": breakdown,
                "supporting_evidence": evidence_items,
                "limitations": limitations,
                "_sort_tuple": (-composite_score, t_svc, svc.identifier, str(svc.id)),
            })

        # Deterministic sorting
        candidates.sort(key=lambda c: c["_sort_tuple"])

        # Assign ranks and probable root cause flags
        ranked_responses: List[RootCauseCandidateResponse] = []
        top_score = candidates[0]["score"] if candidates else 0.0

        for idx, c in enumerate(candidates, start=1):
            # A candidate is marked as probable root cause if it is rank 1 or tied with rank 1
            is_probable = (idx == 1) or (abs(c["score"] - top_score) < 1e-6)
            ranked_responses.append(
                RootCauseCandidateResponse(
                    rank=idx,
                    service_id=c["service_id"],
                    service_slug=c["service_slug"],
                    service_name=c["service_name"],
                    service_identifier=c["service_identifier"],
                    score=c["score"],
                    confidence=c["confidence"],
                    is_probable_root_cause=is_probable,
                    breakdown=c["breakdown"],
                    supporting_evidence=c["supporting_evidence"],
                    limitations=c["limitations"],
                )
            )

        return ranked_responses

