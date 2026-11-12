"""Deterministic, evidence-based root-cause ranking algorithm."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING
from uuid import UUID
from app.models.anomaly import AnomalyEvent
from app.models.service import Service
from app.schemas.correlation import (
    RankingConfidence,
    RankingDimensionScore,
    RootCauseCandidateResponse,
    RootCauseRankingBreakdown,
)

if TYPE_CHECKING:
    from app.services.intelligence.evidence_retriever import MultiSignalBundle


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class RootCauseRanker:
    """Evaluates causal evidence across temporal, topological, blast-radius, severity, and telemetry signals.
    
    Deterministic scoring modes:
    - baseline_v1 (no persisted metrics/logs/traces in window):
      0.35 * temporal + 0.35 * topology + 0.15 * blast_radius + 0.15 * severity
    - multi_signal_v2 (when persisted metrics, logs, and/or trace spans exist):
      Adaptive weights over active signals summing strictly to 1.00:
      temporal (0.20), topology (0.25), blast_radius (0.10), severity (0.10),
      plus available telemetry signals: metric_deviation (0.12), log_evidence (0.10), trace_bottleneck (0.13).
      Unavailable signal families receive weight=0.0 without missing-signal score penalty.
    
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

    # Phase 2 multi-signal base weights (renormalized over active telemetry families)
    V2_BASE_TEMPORAL = 0.20
    V2_BASE_TOPOLOGY = 0.25
    V2_BASE_BLAST = 0.10
    V2_BASE_SEVERITY = 0.10
    V2_BASE_METRIC = 0.12
    V2_BASE_LOG = 0.10
    V2_BASE_TRACE = 0.13

    SEVERITY_FACTORS = {
        "critical": 1.0,
        "high": 0.75,
        "medium": 0.50,
        "low": 0.25,
    }

    CAUSATION_DISCLAIMER = (
        "Probable root-cause candidate inferred from multi-signal telemetry correlation and topological upstream position. "
        "Telemetry correlation does not constitute proven physical causation; verify host health and operational state."
    )

    @classmethod
    def rank_candidates(
        cls,
        participating_services: Dict[UUID, Service],
        events_by_service: Dict[UUID, List[AnomalyEvent]],
        upstream_map: Dict[UUID, Set[UUID]],     # service -> set of services it calls (callees / upstream)
        downstream_map: Dict[UUID, Set[UUID]],   # service -> set of services that call it (callers / downstream)
        topology_edges_exist: bool,
        multi_signal_bundle: Optional["MultiSignalBundle"] = None,
    ) -> List[RootCauseCandidateResponse]:
        """Rank services participating in an anomaly correlation group."""
        service_ids = list(participating_services.keys())
        if not service_ids:
            return []

        has_telemetry = bool(multi_signal_bundle and multi_signal_bundle.has_any_telemetry)
        cov = multi_signal_bundle.summary.coverage if multi_signal_bundle else None
        metrics_avail = bool(cov and cov.metrics_available)
        logs_avail = bool(cov and cov.logs_available)
        traces_avail = bool(cov and cov.traces_available)
        missing_signals = list(cov.missing_signals) if cov else ["metrics", "logs", "traces"]

        if has_telemetry:
            scoring_mode = "multi_signal_v2"
            raw_active_sum = (
                cls.V2_BASE_TEMPORAL
                + cls.V2_BASE_TOPOLOGY
                + cls.V2_BASE_BLAST
                + cls.V2_BASE_SEVERITY
                + (cls.V2_BASE_METRIC if metrics_avail else 0.0)
                + (cls.V2_BASE_LOG if logs_avail else 0.0)
                + (cls.V2_BASE_TRACE if traces_avail else 0.0)
            )
            w_temporal = cls.V2_BASE_TEMPORAL / raw_active_sum
            w_topology = cls.V2_BASE_TOPOLOGY / raw_active_sum
            w_blast = cls.V2_BASE_BLAST / raw_active_sum
            w_severity = cls.V2_BASE_SEVERITY / raw_active_sum
            w_metric = (cls.V2_BASE_METRIC / raw_active_sum) if metrics_avail else 0.0
            w_log = (cls.V2_BASE_LOG / raw_active_sum) if logs_avail else 0.0
            w_trace = (cls.V2_BASE_TRACE / raw_active_sum) if traces_avail else 0.0
        else:
            scoring_mode = "baseline_v1"
            w_temporal = cls.WEIGHT_TEMPORAL
            w_topology = cls.WEIGHT_TOPOLOGY
            w_blast = cls.WEIGHT_BLAST_RADIUS
            w_severity = cls.WEIGHT_SEVERITY
            w_metric = 0.0
            w_log = 0.0
            w_trace = 0.0

        # 1. Global earliest signal time across all participating services
        service_earliest_ts: Dict[UUID, datetime] = {}
        for svc_id in service_ids:
            svc_events = events_by_service.get(svc_id, [])
            if not svc_events:
                continue
            candidates_ts: List[datetime] = [_to_utc(e.occurred_at) for e in svc_events]
            if has_telemetry and multi_signal_bundle:
                prof = multi_signal_bundle.service_profiles.get(svc_id)
                if prof:
                    if prof.earliest_metric_breach_at:
                        candidates_ts.append(_to_utc(prof.earliest_metric_breach_at))
                    if prof.earliest_error_log_at:
                        candidates_ts.append(_to_utc(prof.earliest_error_log_at))
                    if prof.earliest_fault_span_at:
                        candidates_ts.append(_to_utc(prof.earliest_fault_span_at))
            service_earliest_ts[svc_id] = min(candidates_ts)

        if not service_earliest_ts:
            return []

        all_signal_times: List[datetime] = []
        for evs in events_by_service.values():
            all_signal_times.extend([_to_utc(e.occurred_at) for e in evs])
        all_signal_times.extend(service_earliest_ts.values())

        min_time = min(all_signal_times)
        max_time = max(all_signal_times)
        time_span_seconds = max(0.0, (max_time - min_time).total_seconds())

        candidates: List[dict] = []

        for svc_id in service_ids:
            svc = participating_services[svc_id]
            svc_events = events_by_service.get(svc_id, [])
            if not svc_events:
                continue

            earliest_event = min(svc_events, key=lambda e: _to_utc(e.occurred_at))
            t_svc = service_earliest_ts[svc_id]
            delta_from_first_sec = max(0.0, (t_svc - min_time).total_seconds())

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

            # --- Multi-Signal Dimensions (Phase 2) ---
            prof = multi_signal_bundle.service_profiles.get(svc_id) if multi_signal_bundle else None
            s_metric = prof.metric_score if (prof and metrics_avail) else 0.0
            s_log = prof.log_score if (prof and logs_avail) else 0.0
            s_trace = prof.trace_score if (prof and traces_avail) else 0.0

            contradictory_items: List[str] = list(prof.contradictory_items) if prof else []
            neutral_items: List[str] = list(prof.neutral_items) if prof else []

            # Topology vs Temporal contradiction check
            if len(service_ids) > 1 and topology_edges_exist and d_count == 0 and u_count > 0 and s_temporal >= 0.85:
                contradictory_items.append(
                    "Temporal vs topology divergence: downstream caller emitted anomaly earlier than failing upstream dependency."
                )

            raw_composite = (
                w_temporal * s_temporal
                + w_topology * s_topology
                + w_blast * s_blast
                + w_severity * s_severity
                + w_metric * s_metric
                + w_log * s_log
                + w_trace * s_trace
            )
            contradiction_penalty = min(0.20, 0.08 * len(contradictory_items)) if has_telemetry else 0.0
            composite_score = round(max(0.0, min(1.0, raw_composite - contradiction_penalty)), 4)

            # Downstream services explained by this candidate
            affected_downstream_names = sorted(
                participating_services[cid].name
                for cid in reachable_downstream_in_group
                if cid in participating_services and cid != svc_id
            )

            # Supporting Evidence and Limitations
            evidence_items: List[str] = [
                f"First anomalous signal observed at {t_svc.strftime('%H:%M:%S UTC')} on metric '{earliest_event.metric_name}' (value: {earliest_event.observed_value:.1f}).",
                f"Total {len(svc_events)} anomaly events registered for service in this time window.",
            ]
            if d_count > 0:
                evidence_items.append(
                    f"Direct/transitive upstream dependency for: {', '.join(affected_downstream_names)}."
                )
            if prof and prof.supporting_items:
                for item in prof.supporting_items:
                    if item not in evidence_items:
                        evidence_items.append(item)

            limitations: List[str] = [cls.CAUSATION_DISCLAIMER]
            if len(service_ids) == 1:
                limitations.append(
                    "Single affected service; root cause candidate is self-contained with no observed downstream propagation."
                )
            elif not topology_edges_exist:
                limitations.append(
                    "Service dependency graph has no registered edges between these services; ranking relies primarily on temporal and telemetry signals."
                )
            if missing_signals:
                limitations.append(
                    f"Missing telemetry signal(s): {', '.join(missing_signals)} (treated neutrally without score penalty)."
                )
            if contradictory_items:
                limitations.append(
                    f"Detected {len(contradictory_items)} contradictory signal indicator(s); confidence adjusted downward."
                )

            # Build transparent dimension breakdowns
            metric_reason = (
                f"Metric deviation score {s_metric:.2f} (max deviation {prof.max_metric_deviation_pct:.1f}%)."
                if (metrics_avail and prof and prof.has_anomalous_metrics)
                else (
                    "Persisted metrics within normal baseline bounds in window."
                    if (metrics_avail and prof and prof.has_metric_samples)
                    else "No persisted metric samples available in correlation window."
                )
            )
            log_reason = (
                f"Log evidence score {s_log:.2f} ({prof.distinct_error_keys} distinct error traces, {prof.error_logs_count} ERROR/CRITICAL entries)."
                if (logs_avail and prof and prof.has_logs)
                else "No persisted structured logs available in correlation window."
            )
            trace_reason = (
                f"Trace bottleneck score {s_trace:.2f} (owns {prof.bottleneck_traces_owned} bottleneck(s) and {prof.origin_error_traces_owned} origin error trace(s))."
                if (traces_avail and prof and prof.has_traces)
                else "No persisted distributed trace spans available in correlation window."
            )

            breakdown = RootCauseRankingBreakdown(
                temporal_precedence=RankingDimensionScore(
                    score=round(s_temporal, 4),
                    weight=round(w_temporal, 4),
                    weighted_score=round(w_temporal * s_temporal, 4),
                    reason=t_reason,
                ),
                topological_position=RankingDimensionScore(
                    score=round(s_topology, 4),
                    weight=round(w_topology, 4),
                    weighted_score=round(w_topology * s_topology, 4),
                    reason=topo_reason,
                ),
                blast_radius=RankingDimensionScore(
                    score=round(s_blast, 4),
                    weight=round(w_blast, 4),
                    weighted_score=round(w_blast * s_blast, 4),
                    reason=blast_reason,
                ),
                severity_magnitude=RankingDimensionScore(
                    score=round(s_severity, 4),
                    weight=round(w_severity, 4),
                    weighted_score=round(w_severity * s_severity, 4),
                    reason=sev_reason,
                ),
                metric_deviation=RankingDimensionScore(
                    score=round(s_metric, 4),
                    weight=round(w_metric, 4),
                    weighted_score=round(w_metric * s_metric, 4),
                    reason=metric_reason,
                    available=metrics_avail,
                ) if has_telemetry else None,
                log_evidence=RankingDimensionScore(
                    score=round(s_log, 4),
                    weight=round(w_log, 4),
                    weighted_score=round(w_log * s_log, 4),
                    reason=log_reason,
                    available=logs_avail,
                ) if has_telemetry else None,
                trace_bottleneck=RankingDimensionScore(
                    score=round(s_trace, 4),
                    weight=round(w_trace, 4),
                    weighted_score=round(w_trace * s_trace, 4),
                    reason=trace_reason,
                    available=traces_avail,
                ) if has_telemetry else None,
            )

            # Bounded evidence references for downstream drill-down
            ev_refs: Dict[str, Any] = {
                "anomaly_event_ids": [str(e.id) for e in svc_events[:20]],
                "metric_names": list(prof.referenced_metric_names) if prof else [],
                "log_ids": list(prof.referenced_log_ids) if prof else [],
                "trace_ids": list(prof.referenced_trace_ids) if prof else [],
                "bottleneck_span_ids": list(prof.referenced_span_ids) if prof else [],
            }

            candidates.append({
                "service_id": svc.id,
                "service_slug": svc.slug,
                "service_name": svc.name,
                "service_identifier": svc.identifier,
                "score": composite_score,
                "d_count": d_count,
                "s_trace": s_trace,
                "contradiction_count": len(contradictory_items),
                "breakdown": breakdown,
                "supporting_evidence": evidence_items,
                "limitations": limitations,
                "contradictory_evidence": contradictory_items,
                "neutral_signals": neutral_items,
                "missing_signals": missing_signals,
                "primary_suspected_operation": prof.suspected_operation if prof else None,
                "affected_downstream_services": affected_downstream_names,
                "evidence_references": ev_refs,
                "scoring_mode": scoring_mode,
                "_sort_tuple": (-composite_score, t_svc, svc.identifier, str(svc.id)),
            })

        # Deterministic sorting
        candidates.sort(key=lambda c: c["_sort_tuple"])

        # Assign ranks, calibrated confidence, and probable root cause flags
        ranked_responses: List[RootCauseCandidateResponse] = []
        top_score = candidates[0]["score"] if candidates else 0.0
        second_score = candidates[1]["score"] if len(candidates) > 1 else 0.0
        margin = top_score - second_score if len(candidates) > 1 else 1.0
        ambiguous_tie = len(candidates) > 1 and margin < 0.05

        for idx, c in enumerate(candidates, start=1):
            c_score = c["score"]
            # Confidence calibration
            if len(service_ids) == 1:
                confidence = RankingConfidence.MEDIUM
            elif not topology_edges_exist and not (has_telemetry and c["s_trace"] >= 0.70):
                confidence = RankingConfidence.LOW
            elif c["contradiction_count"] >= 2:
                confidence = RankingConfidence.LOW
            elif ambiguous_tie and idx <= 2:
                confidence = RankingConfidence.MEDIUM if c_score >= 0.45 else RankingConfidence.LOW
                c["limitations"].append(
                    f"Close competition between top candidates (score margin {margin:.3f}); ambiguity remains."
                )
            elif (
                c_score >= 0.68
                and (c["d_count"] > 0 or (has_telemetry and c["s_trace"] >= 0.75))
                and c["contradiction_count"] == 0
                and topology_edges_exist
            ):
                confidence = RankingConfidence.HIGH
            elif c_score >= 0.45:
                confidence = RankingConfidence.MEDIUM
            else:
                confidence = RankingConfidence.LOW

            is_probable = (idx == 1) or (abs(c_score - top_score) < 1e-6)
            ranked_responses.append(
                RootCauseCandidateResponse(
                    rank=idx,
                    service_id=c["service_id"],
                    service_slug=c["service_slug"],
                    service_name=c["service_name"],
                    service_identifier=c["service_identifier"],
                    score=c_score,
                    confidence=confidence,
                    is_probable_root_cause=is_probable,
                    breakdown=c["breakdown"],
                    supporting_evidence=c["supporting_evidence"],
                    limitations=c["limitations"],
                    contradictory_evidence=c["contradictory_evidence"],
                    neutral_signals=c["neutral_signals"],
                    missing_signals=c["missing_signals"],
                    primary_suspected_operation=c["primary_suspected_operation"],
                    affected_downstream_services=c["affected_downstream_services"],
                    evidence_references=c["evidence_references"],
                    scoring_mode=c["scoring_mode"],
                )
            )

        return ranked_responses

