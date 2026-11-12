"""Core correlation engine grouping cross-service anomalies and explaining causal links."""

import hashlib
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyEvent
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.repositories.anomaly_repository import AnomalyEventRepository
from app.repositories.service_dependency_repository import ServiceDependencyRepository
from app.repositories.service_repository import ServiceRepository
from app.schemas.correlation import (
    CorrelationConfig,
    CorrelationEvaluationResponse,
    CorrelationGroupResponse,
    CorrelatedEventSummary,
)
from app.services.correlation.ranker import RootCauseRanker
from app.services.intelligence.evidence_retriever import MultiSignalEvidenceRetriever


class CorrelationEngine:
    """Deterministic cross-service anomaly correlation and root-cause discovery engine."""

    def __init__(self, db: Session):
        self.db = db
        self.event_repo = AnomalyEventRepository(db)
        self.dependency_repo = ServiceDependencyRepository(db)
        self.service_repo = ServiceRepository(db)
        self.evidence_retriever = MultiSignalEvidenceRetriever(db)

    @staticmethod
    def generate_correlation_key(project_id: UUID, event_ids: List[UUID]) -> str:
        """Deterministic hash of project_id and sorted event UUIDs to guarantee evaluation idempotency."""
        sorted_strs = sorted(str(eid) for eid in event_ids)
        payload = f"{project_id}:" + ",".join(sorted_strs)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def evaluate(
        self,
        project_id: UUID,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        config: Optional[CorrelationConfig] = None,
    ) -> List[CorrelationGroupResponse]:
        """Discover, group, and rank correlated cross-service anomalies for a project."""
        active_config = config or CorrelationConfig()

        now_utc = datetime.now(timezone.utc)
        if end_time is None:
            end_time = now_utc
        if start_time is None:
            start_time = end_time - timedelta(seconds=active_config.time_window_seconds)

        if start_time > end_time:
            raise ValueError(
                f"Invalid time window: start_time ({start_time.isoformat()}) must be before "
                f"end_time ({end_time.isoformat()})."
            )

        # 1. Fetch anomaly events strictly within project boundary and time window
        events_query = (
            self.db.query(AnomalyEvent)
            .filter(
                AnomalyEvent.project_id == project_id,
                AnomalyEvent.occurred_at >= start_time,
                AnomalyEvent.occurred_at <= end_time,
            )
            .order_by(AnomalyEvent.occurred_at.asc(), AnomalyEvent.id.asc())
            .limit(active_config.max_events)
        )
        anomaly_events = events_query.all()

        if not anomaly_events:
            return []

        # 2. Fetch all services and dependencies for the project
        services_list = self.service_repo.get_by_project(project_id)
        services_map: Dict[UUID, Service] = {s.id: s for s in services_list}
        dependencies = self.dependency_repo.list_by_project(project_id)

        # 3. Build directed dependency structures:
        # upstream_map[u]: set of services that u calls (callees)
        # downstream_map[u]: set of services that call u (callers)
        # undirected_adj: for connected-component analysis among anomalous services
        upstream_map: Dict[UUID, Set[UUID]] = {s.id: set() for s in services_list}
        downstream_map: Dict[UUID, Set[UUID]] = {s.id: set() for s in services_list}
        undirected_adj: Dict[UUID, Set[UUID]] = {s.id: set() for s in services_list}

        for dep in dependencies:
            src = dep.source_service_id  # caller
            tgt = dep.target_service_id  # callee
            if src in upstream_map and tgt in upstream_map:
                upstream_map[src].add(tgt)
                downstream_map[tgt].add(src)
                undirected_adj[src].add(tgt)
                undirected_adj[tgt].add(src)

        # 4. Group events by service
        events_by_service: Dict[UUID, List[AnomalyEvent]] = {}
        for event in anomaly_events:
            events_by_service.setdefault(event.service_id, []).append(event)

        active_service_ids = set(events_by_service.keys())
        topology_edges_exist = len(dependencies) > 0

        # 5. Temporal Cascade Event Clustering
        # In a distributed system, anomaly events are causally related if:
        # a) They occur within max_cascade_delay_seconds of each other, AND
        # b) Either:
        #    - They occur on the same service (multiple metric anomalies during an incident)
        #    - Their services are directly or transitively linked in the dependency graph
        #    - Topology is unmapped (provisional project-level temporal proximity)
        n_events = len(anomaly_events)
        event_adj: Dict[int, List[int]] = {i: [] for i in range(n_events)}
        max_delay = active_config.max_cascade_delay_seconds

        for i in range(n_events):
            ev_i = anomaly_events[i]
            for j in range(i + 1, n_events):
                ev_j = anomaly_events[j]
                delta_sec = abs((ev_j.occurred_at - ev_i.occurred_at).total_seconds())
                if delta_sec > max_delay:
                    # Events separated by more than max_cascade_delay_seconds represent separate incidents
                    continue

                same_svc = ev_i.service_id == ev_j.service_id
                topo_connected = ev_j.service_id in undirected_adj.get(ev_i.service_id, set())
                unmapped_topology = not topology_edges_exist

                if same_svc or topo_connected or unmapped_topology:
                    event_adj[i].append(j)
                    event_adj[j].append(i)

        # 5. Temporal Cascade Event Clustering with Incident Duration Bounds
        # Prevents temporal chaining where transitive single-linkage clustering
        # forms excessively long, runaway incidents spanning across separate failures.
        max_duration = (
            active_config.max_incident_duration_seconds
            if active_config.max_incident_duration_seconds is not None
            else max_delay
        )

        visited_evs: Set[int] = set()
        event_clusters: List[List[AnomalyEvent]] = []

        for i in range(n_events):
            if i in visited_evs:
                continue

            cluster_ev_indices: List[int] = [i]
            visited_evs.add(i)
            cluster_min_t = anomaly_events[i].occurred_at
            cluster_max_t = anomaly_events[i].occurred_at

            q: deque[int] = deque([i])

            while q:
                curr = q.popleft()
                for neighbor in event_adj.get(curr, []):
                    if neighbor not in visited_evs:
                        nbr_t = anomaly_events[neighbor].occurred_at
                        cand_min_t = min(cluster_min_t, nbr_t)
                        cand_max_t = max(cluster_max_t, nbr_t)
                        timespan = (cand_max_t - cand_min_t).total_seconds()
                        if timespan <= max_duration:
                            visited_evs.add(neighbor)
                            cluster_ev_indices.append(neighbor)
                            cluster_min_t = cand_min_t
                            cluster_max_t = cand_max_t
                            q.append(neighbor)

            cluster_evs = [anomaly_events[idx] for idx in cluster_ev_indices]
            cluster_evs.sort(key=lambda e: (e.occurred_at, e.id))
            event_clusters.append(cluster_evs)

        # 6. Form Correlation Groups
        results: List[CorrelationGroupResponse] = []

        for cluster_events in event_clusters:
            # Check min_events_per_group threshold
            if len(cluster_events) < active_config.min_events_per_group:
                continue

            cluster_service_ids = {e.service_id for e in cluster_events}
            event_ids = [e.id for e in cluster_events]
            corr_key = self.generate_correlation_key(project_id, event_ids)
            group_min_time = cluster_events[0].occurred_at
            group_max_time = cluster_events[-1].occurred_at

            # Cluster topology completeness check:
            # Complete only if project has topology AND all services in this cluster are connected by dependency edges
            cluster_topology_complete = True
            if not topology_edges_exist:
                cluster_topology_complete = False
            elif len(cluster_service_ids) > 1:
                first_sid = next(iter(cluster_service_ids))
                seen_sids = {first_sid}
                sq: deque[UUID] = deque([first_sid])
                while sq:
                    curr_s = sq.popleft()
                    for nbr in undirected_adj.get(curr_s, set()):
                        if nbr in cluster_service_ids and nbr not in seen_sids:
                            seen_sids.add(nbr)
                            sq.append(nbr)
                if seen_sids != cluster_service_ids:
                    cluster_topology_complete = False

            # Retrieve multi-signal telemetry evidence & rank root causes deterministically
            cluster_services = {sid: services_map[sid] for sid in cluster_service_ids if sid in services_map}
            cluster_events_by_svc: Dict[UUID, List[AnomalyEvent]] = {}
            for ev in cluster_events:
                cluster_events_by_svc.setdefault(ev.service_id, []).append(ev)

            multi_signal_bundle = self.evidence_retriever.retrieve(
                project_id=project_id,
                window_start=group_min_time,
                window_end=group_max_time,
                services_map=cluster_services,
                anomaly_events=cluster_events,
                downstream_map=downstream_map,
                topology_complete=cluster_topology_complete,
                all_services_map=services_map,
            )

            ranked_candidates = RootCauseRanker.rank_candidates(
                participating_services=cluster_services,
                events_by_service=cluster_events_by_svc,
                upstream_map=upstream_map,
                downstream_map=downstream_map,
                topology_edges_exist=cluster_topology_complete,
                multi_signal_bundle=multi_signal_bundle,
            )

            # Build explainability per participating anomaly event
            earliest_service_id = cluster_events[0].service_id
            participating_summaries: List[CorrelatedEventSummary] = []

            for ev in cluster_events:
                svc = services_map.get(ev.service_id)
                svc_name = svc.name if svc else "Unknown Service"
                svc_ident = svc.identifier if svc else "unknown"

                # Explain reason for inclusion
                if ev.service_id == earliest_service_id:
                    reason = (
                        f"Initiating anomaly in correlation window on metric '{ev.metric_name}' "
                        f"observed at {ev.occurred_at.strftime('%H:%M:%S UTC')}."
                    )
                    relevance = 1.0
                elif topology_edges_exist and earliest_service_id in upstream_map.get(ev.service_id, set()):
                    delta_s = (ev.occurred_at - group_min_time).total_seconds()
                    initiator_name = services_map[earliest_service_id].name if earliest_service_id in services_map else "upstream"
                    reason = (
                        f"Downstream cascade: caller of failing upstream '{initiator_name}' "
                        f"(latency propagation delta: +{delta_s:.1f}s)."
                    )
                    relevance = 0.90
                elif topology_edges_exist and ev.service_id in upstream_map.get(earliest_service_id, set()):
                    delta_s = (ev.occurred_at - group_min_time).total_seconds()
                    reason = f"Upstream dependency of failing service (delta: +{delta_s:.1f}s)."
                    relevance = 0.85
                elif topology_edges_exist:
                    reason = "Connected in project service dependency topology within time window."
                    relevance = 0.70
                else:
                    delta_s = (ev.occurred_at - group_min_time).total_seconds()
                    reason = f"Co-temporal occurrence (+{delta_s:.1f}s apart) in project with unmapped topology."
                    relevance = 0.50

                participating_summaries.append(
                    CorrelatedEventSummary(
                        event_id=ev.id,
                        service_id=ev.service_id,
                        service_name=svc_name,
                        service_identifier=svc_ident,
                        metric_name=ev.metric_name,
                        observed_value=ev.observed_value,
                        expected_baseline=ev.expected_baseline,
                        deviation_pct=ev.deviation_pct,
                        severity=ev.severity,
                        occurred_at=ev.occurred_at,
                        relevance_score=relevance,
                        correlation_reason=reason,
                    )
                )

            top_candidate = ranked_candidates[0] if ranked_candidates else None
            summary_text = (
                f"Correlated {len(cluster_events)} anomalies across {len(cluster_service_ids)} services. "
                f"Probable root-cause candidate: {top_candidate.service_name if top_candidate else 'None'} "
                f"(score: {top_candidate.score:.2f}, confidence: {top_candidate.confidence.value if top_candidate else 'N/A'})."
            )

            # Overall group confidence score
            group_conf = top_candidate.score if top_candidate else 0.5
            if not cluster_topology_complete and not (
                multi_signal_bundle.has_any_telemetry and top_candidate and top_candidate.breakdown.trace_bottleneck and top_candidate.breakdown.trace_bottleneck.score >= 0.75
            ):
                group_conf = round(group_conf * 0.70, 4)

            primary_op = (
                (top_candidate.primary_suspected_operation if top_candidate and top_candidate.primary_suspected_operation else None)
                or multi_signal_bundle.summary.primary_suspected_operation
            )
            uncertainty_notes = multi_signal_bundle.summary.uncertainty_notes
            uncertainty_summary = "; ".join(uncertainty_notes) if uncertainty_notes else None

            group_resp = CorrelationGroupResponse(
                id=UUID(int=0),  # Will be assigned during persistence or generated
                project_id=project_id,
                correlation_key=corr_key,
                time_window_start=group_min_time,
                time_window_end=group_max_time,
                status="ACTIVE",
                summary=summary_text,
                confidence_score=group_conf,
                topology_complete=cluster_topology_complete,
                events_count=len(cluster_events),
                participating_events=participating_summaries,
                ranked_candidates=ranked_candidates,
                evidence_summary=multi_signal_bundle.summary,
                primary_suspected_operation=primary_op,
                uncertainty_summary=uncertainty_summary,
                created_at=datetime.now(timezone.utc),
            )
            results.append(group_resp)

        return results

