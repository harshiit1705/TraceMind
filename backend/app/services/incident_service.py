import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.correlation import CorrelationGroup
from app.models.investigation import Investigation
from app.models.finding import Finding
from app.models.recommendation import Recommendation
from app.repositories.incident_repository import IncidentRepository
from app.repositories.investigation_repository import InvestigationRepository
from app.services.project_service import ProjectService
from app.services.demo.evidence_provider import get_evidence_provider
from app.schemas.common import IncidentStatus
from app.schemas.incident import (
    IncidentCreateRequest,
    IncidentDetailResponse,
    IncidentEventResponse,
    IncidentResponse,
    IncidentStatusUpdateRequest,
    TimelineResponse,
)
from app.schemas.evidence import EvidenceResponse, EvidenceListResponse
from app.schemas.investigation import InvestigationDetailResponse


class IncidentNotFoundError(Exception):
    """Raised when the requested incident does not exist."""
    pass


class InvalidStatusTransitionError(Exception):
    """Raised when an incident status transition violates the validated lifecycle policy."""
    pass


class CorrelationGroupNotFoundError(Exception):
    """Raised when the requested correlation group does not exist."""
    pass


class ProjectIsolationError(Exception):
    """Raised when a correlation group belongs to a different project."""
    pass


class CorrelationGroupAlreadyLinkedError(Exception):
    """Raised when a correlation group is already linked to an incident."""
    pass


ALLOWED_TRANSITIONS: Dict[IncidentStatus, Set[IncidentStatus]] = {
    IncidentStatus.DETECTED: {IncidentStatus.INVESTIGATING, IncidentStatus.ACKNOWLEDGED},
    IncidentStatus.INVESTIGATING: {IncidentStatus.ACKNOWLEDGED, IncidentStatus.MITIGATED, IncidentStatus.RESOLVED},
    IncidentStatus.ACKNOWLEDGED: {IncidentStatus.INVESTIGATING, IncidentStatus.MITIGATED, IncidentStatus.RESOLVED},
    IncidentStatus.MITIGATED: {IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED},
    IncidentStatus.RESOLVED: set(),  # No further transitions in this sprint
}


class IncidentService:
    def __init__(self, db: Session):
        self.db = db
        self.incident_repo = IncidentRepository(db)
        self.investigation_repo = InvestigationRepository(db)
        self.project_service = ProjectService(db)
        self.evidence_provider = get_evidence_provider()

    def ensure_default_seed(self) -> None:
        """Seeds default incidents including INC-8492 if missing."""
        existing = self.incident_repo.get_by_number("INC-8492")
        if existing:
            return

        proj = self.project_service.ensure_default_seed()

        # INC-8492 (Critical Sev-0)
        inc_8492 = Incident(
            project_id=proj.id,
            incident_number="INC-8492",
            title="Database connection pool exhaustion causing cascading payment & checkout timeouts",
            severity="CRITICAL",
            status="INVESTIGATING",
            started_at=datetime(2024, 10, 24, 14, 18, 0, tzinfo=timezone.utc),
            commander_name="Alex Chen",
            commander_role="Staff SRE",
            root_cause_summary="Zombie idle transactions holding exclusive row locks on orders_ledger partition",
            affected_services=["API Gateway", "Order Service", "Payment Service", "PostgreSQL Primary (Aurora)"],
            summary="Continuous transactions held row-level exclusive locks against partition orders_ledger_2024_q2, exhausting max connections within 180s.",
            is_demo=True
        )
        self.db.add(inc_8492)
        self.db.commit()
        self.db.refresh(inc_8492)

        # Timeline events for INC-8492
        events_data = [
            {
                "timestamp": datetime(2024, 10, 24, 14, 17, 42, tzinfo=timezone.utc),
                "title": "orders_ledger Lock Contention Detected",
                "event_type": "anomaly",
                "source": "Loki Log Stream",
                "description": "Exclusive row lock held by 42 zombie backend PID threads on partition orders_ledger_2024_q2."
            },
            {
                "timestamp": datetime(2024, 10, 24, 14, 18, 10, tzinfo=timezone.utc),
                "title": "Aurora DB Pool 98% Used",
                "event_type": "alert",
                "source": "Prometheus Anomaly Alert",
                "description": "980 of 1,000 max connections exhausted on cluster-02. Connection acquisition timeout exceeded."
            },
            {
                "timestamp": datetime(2024, 10, 24, 14, 18, 32, tzinfo=timezone.utc),
                "title": "Payment Threads Blocked",
                "event_type": "anomaly",
                "source": "APM Tracer",
                "description": "Tomcat executor thread pool pegged at 94% busy wait awaiting database responses."
            },
            {
                "timestamp": datetime(2024, 10, 24, 14, 19, 5, tzinfo=timezone.utc),
                "title": "Gateway 504 Timeouts to Clients",
                "event_type": "alert",
                "source": "Edge Gateway Monitor",
                "description": "Public checkout traffic experiencing 2.84% failure rate with 504 Gateway Timeout responses."
            },
            {
                "timestamp": datetime(2024, 10, 24, 14, 20, 27, tzinfo=timezone.utc),
                "title": "PagerDuty Escalation Acknowledged",
                "event_type": "human",
                "source": "PagerDuty Sync",
                "description": "Staff SRE Alex Chen acknowledged Sev-0 escalation and opened War Room."
            }
        ]

        for ev in events_data:
            event = IncidentEvent(incident_id=inc_8492.id, **ev)
            self.db.add(event)

        # Additional companion incidents matching frontend catalog
        other_incidents = [
            {
                "incident_number": "INC-8489",
                "title": "Elevated 502 Bad Gateway responses on /api/v2/checkout",
                "severity": "HIGH",
                "status": "ACKNOWLEDGED",
                "started_at": datetime(2024, 10, 24, 14, 22, 0, tzinfo=timezone.utc),
                "commander_name": "Maria Vance",
                "commander_role": "Platform Lead",
                "root_cause_summary": "Upstream gateway timeouts due to connection pool contention downstream",
                "affected_services": ["API Gateway", "Order Service"],
                "is_demo": True
            },
            {
                "incident_number": "INC-8488",
                "title": "Kafka consumer lag threshold exceeded on topic: order-events",
                "severity": "MEDIUM",
                "status": "MITIGATED",
                "started_at": datetime(2024, 10, 24, 13, 40, 0, tzinfo=timezone.utc),
                "commander_name": "David Kim",
                "commander_role": "Backend Engineer",
                "root_cause_summary": "Consumer rebalance loop triggered by temporary heartbeat timeout",
                "affected_services": ["Notification Service"],
                "is_demo": True
            },
            {
                "incident_number": "INC-8485",
                "title": "Redis session cache cluster memory usage exceeded 85% warning watermark",
                "severity": "LOW",
                "status": "ACKNOWLEDGED",
                "started_at": datetime(2024, 10, 24, 12, 15, 0, tzinfo=timezone.utc),
                "commander_name": "Sarah Jenkins",
                "commander_role": "Infrastructure Engineer",
                "root_cause_summary": "Key TTL expiration policy backlog in partition shard-03",
                "affected_services": ["User Service"],
                "is_demo": True
            },
            {
                "incident_number": "INC-8481",
                "title": "Core authentication service DNS resolution intermittent timeouts",
                "severity": "CRITICAL",
                "status": "RESOLVED",
                "started_at": datetime(2024, 10, 24, 8, 10, 0, tzinfo=timezone.utc),
                "resolved_at": datetime(2024, 10, 24, 8, 34, 12, tzinfo=timezone.utc),
                "commander_name": "Alex Chen",
                "commander_role": "Staff SRE",
                "root_cause_summary": "CoreDNS replica pod evicted due to node memory pressure",
                "affected_services": ["Auth Service", "API Gateway"],
                "is_demo": True
            },
            {
                "incident_number": "INC-8479",
                "title": "S3 static asset upload throttling in us-east-1 during promotional event",
                "severity": "HIGH",
                "status": "RESOLVED",
                "started_at": datetime(2024, 10, 23, 19, 30, 0, tzinfo=timezone.utc),
                "resolved_at": datetime(2024, 10, 23, 20, 15, 10, tzinfo=timezone.utc),
                "commander_name": "Elena Rostova",
                "commander_role": "DevOps Lead",
                "root_cause_summary": "Partition key prefix hotspotting in media bucket",
                "affected_services": ["Search Indexer"],
                "is_demo": True
            }
        ]

        for other_data in other_incidents:
            inc = Incident(project_id=proj.id, **other_data)
            self.db.add(inc)

        # Baseline investigation contract for INC-8492
        inv = Investigation(
            incident_id=inc_8492.id,
            agent_name="Autonomous Agent #4",
            status="COMPLETED",
            summary="Autonomous investigation correlated database connection pool exhaustion with zombie transaction row locks.",
            correlation_scope=42,
            spans_analyzed=128400,
            confidence_score=94.0,
            is_demo=True,
            started_at=datetime(2024, 10, 24, 14, 18, 10, tzinfo=timezone.utc),
            completed_at=datetime(2024, 10, 24, 14, 33, 10, tzinfo=timezone.utc)
        )
        self.db.add(inv)
        self.db.commit()
        self.db.refresh(inv)

        finding = Finding(
            investigation_id=inv.id,
            rank=1,
            title="Zombie idle transactions holding locks on orders_ledger partition",
            probable_root_cause="Uncommitted batch cron job held row-level exclusive locks against orders_ledger partition, starving JDBC connection pool.",
            explanation="pg_stat_activity records show 42 backend threads blocked waiting on PID 18492 for >1,080 seconds.",
            status="CONFIRMED",
            confidence_score=94.0,
            affected_services=["PostgreSQL Primary (Aurora)", "Payment Service", "Order Service"],
            supporting_evidence_ids=["ev-101-db-pool", "ev-105-lock-log"],
            is_demo=True
        )
        self.db.add(finding)

        rec = Recommendation(
            investigation_id=inv.id,
            finding_id=finding.id,
            title="Execute Runbook RB-402: Terminate Idle Transactions",
            action_type="immediate",
            description="Immediately relieves lock contention by terminating idle transactions older than 5 minutes.",
            command_snippet="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND query_start < NOW() - INTERVAL '5 min';",
            risk_level="LOW",
            is_dry_run_safe=True,
            requires_human_approval=True,
            is_demo=True
        )
        self.db.add(rec)
        self.db.commit()

    def list_incidents(
        self,
        project_id: Optional[UUID] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[IncidentResponse], int]:
        self.ensure_default_seed()
        items, total = self.incident_repo.get_list(
            project_id=project_id,
            status=status,
            severity=severity,
            skip=skip,
            limit=limit,
        )
        return [IncidentResponse.model_validate(inc) for inc in items], total

    def get_incident_by_id_or_number(self, identifier: str) -> Optional[IncidentDetailResponse]:
        self.ensure_default_seed()
        # Attempt UUID lookup first, fallback to incident_number lookup
        incident = None
        try:
            val_uuid = UUID(identifier)
            incident = self.incident_repo.get_by_id(val_uuid)
        except ValueError:
            pass

        if not incident:
            incident = self.incident_repo.get_by_number(identifier)

        if not incident:
            return None

        events = self.incident_repo.get_events(incident.id)
        incident_dict = IncidentResponse.model_validate(incident).model_dump()
        incident_dict["events"] = [IncidentEventResponse.model_validate(e) for e in events]
        return IncidentDetailResponse(**incident_dict)

    def get_timeline(self, identifier: str) -> Optional[TimelineResponse]:
        incident_detail = self.get_incident_by_id_or_number(identifier)
        if not incident_detail:
            return None
        return TimelineResponse(
            incident_id=incident_detail.id,
            incident_number=incident_detail.incident_number,
            events=incident_detail.events
        )

    def get_evidence(self, identifier: str) -> Optional[EvidenceListResponse]:
        incident_detail = self.get_incident_by_id_or_number(identifier)
        if not incident_detail:
            return None

        items = self.evidence_provider.get_evidence_for_incident(
            incident_id=incident_detail.id,
            incident_number=incident_detail.incident_number
        )
        return EvidenceListResponse(
            incident_id=incident_detail.id,
            incident_number=incident_detail.incident_number,
            total_count=len(items),
            items=items,
            is_demo_scenario=True
        )

    def get_investigation(self, investigation_id: UUID) -> Optional[InvestigationDetailResponse]:
        self.ensure_default_seed()
        inv = self.investigation_repo.get_by_id(investigation_id)
        if not inv:
            return None
        return InvestigationDetailResponse.model_validate(inv)

    def get_investigation_for_incident(self, incident_identifier: str) -> Optional[InvestigationDetailResponse]:
        incident_detail = self.get_incident_by_id_or_number(incident_identifier)
        if not incident_detail:
            return None
        inv = self.investigation_repo.get_by_incident_id(incident_detail.id)
        if not inv:
            return None
        return InvestigationDetailResponse.model_validate(inv)

    def sync_incident_for_correlation_group(
        self,
        correlation_group: CorrelationGroup,
        superseded_groups: Optional[List[CorrelationGroup]] = None,
        commit: bool = True,
    ) -> Incident:
        """Automatically create a persisted incident for a correlation group or update a superseded incident."""
        # 1. Idempotency check: an incident already references this correlation_group_id
        existing = self.incident_repo.get_by_correlation_group_id(correlation_group.id)
        if existing:
            return existing

        # 2. Check for an unambiguous predecessor in superseded_groups
        if superseded_groups and len(superseded_groups) == 1:
            predecessor_group = superseded_groups[0]
            predecessor_incident = self.incident_repo.get_by_correlation_group_id(predecessor_group.id)
            if predecessor_incident:
                # Update correlation linkage to the expanded group
                predecessor_incident.correlation_group_id = correlation_group.id

                # Merge affected services from new group
                new_services = set(predecessor_incident.affected_services or [])
                for assoc in correlation_group.event_associations:
                    if assoc.anomaly_event and assoc.anomaly_event.service:
                        new_services.add(assoc.anomaly_event.service.name)
                predecessor_incident.affected_services = sorted(list(new_services))

                # Escalate severity if new group has higher severity
                sev_weights = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
                current_sev_weight = sev_weights.get(predecessor_incident.severity.upper(), 1)
                max_new_sev = predecessor_incident.severity.upper()
                for assoc in correlation_group.event_associations:
                    if assoc.anomaly_event and assoc.anomaly_event.severity:
                        ev_sev = assoc.anomaly_event.severity.upper()
                        if sev_weights.get(ev_sev, 1) > current_sev_weight:
                            current_sev_weight = sev_weights.get(ev_sev, 1)
                            max_new_sev = ev_sev
                predecessor_incident.severity = max_new_sev

                if correlation_group.summary:
                    predecessor_incident.summary = correlation_group.summary

                # Append timeline audit event
                now_utc = datetime.now(timezone.utc)
                event = IncidentEvent(
                    id=uuid.uuid4(),
                    incident_id=predecessor_incident.id,
                    timestamp=now_utc,
                    title="Correlation Cluster Expanded",
                    event_type="anomaly",
                    source="Correlation Engine",
                    description=(
                        f"Incident correlation scope updated to include expanded cascade "
                        f"({len(correlation_group.event_associations)} events). "
                        f"Predecessor group {predecessor_group.id} marked SUPERSEDED."
                    ),
                    payload={
                        "superseded_group_id": str(predecessor_group.id),
                        "new_correlation_group_id": str(correlation_group.id),
                    },
                )
                self.db.add(event)
                if commit:
                    self.db.commit()
                    self.db.refresh(predecessor_incident)
                else:
                    self.db.flush()
                return predecessor_incident

        # 3. Create a brand new incident starting at DETECTED
        affected_services = set()
        sev_weights = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        max_sev = "MEDIUM"
        max_weight = 2

        for assoc in correlation_group.event_associations:
            if assoc.anomaly_event:
                if assoc.anomaly_event.service:
                    affected_services.add(assoc.anomaly_event.service.name)
                if assoc.anomaly_event.severity:
                    ev_sev = assoc.anomaly_event.severity.upper()
                    if sev_weights.get(ev_sev, 1) > max_weight:
                        max_weight = sev_weights.get(ev_sev, 1)
                        max_sev = ev_sev

        services_list = sorted(list(affected_services))

        # Title derivation from top root-cause candidate or services
        title = "Correlated anomaly cascade"
        if correlation_group.root_cause_candidates:
            top_cand = correlation_group.root_cause_candidates[0]
            cand_svc = top_cand.service.name if top_cand.service else None
            if cand_svc:
                title = f"Degradation cascade initiating from {cand_svc}"
            elif services_list:
                title = f"Correlated anomaly cascade across {', '.join(services_list[:3])}"
        elif services_list:
            title = f"Correlated anomaly cascade across {', '.join(services_list[:3])}"

        # Safe incident number generation with retry on collision using savepoints
        new_inc = None
        max_attempts = 5
        for attempt in range(max_attempts):
            inc_number = self.incident_repo.generate_next_incident_number()
            inc_id = uuid.uuid4()
            incident_candidate = Incident(
                id=inc_id,
                project_id=correlation_group.project_id,
                correlation_group_id=correlation_group.id,
                incident_number=inc_number,
                title=title,
                severity=max_sev,
                status=IncidentStatus.DETECTED.value,
                started_at=correlation_group.time_window_start,
                commander_name="Unassigned",
                commander_role="SRE",
                affected_services=services_list,
                summary=correlation_group.summary,
                is_demo=False,
            )
            initial_event = IncidentEvent(
                id=uuid.uuid4(),
                incident_id=inc_id,
                timestamp=correlation_group.time_window_start,
                title="Incident Automatically Detected",
                event_type="anomaly",
                source="Correlation Engine",
                description=correlation_group.summary or "Anomalies correlated across service boundaries.",
                payload={
                    "correlation_group_id": str(correlation_group.id),
                    "confidence_score": correlation_group.confidence_score,
                },
            )
            try:
                with self.db.begin_nested():
                    self.db.add(incident_candidate)
                    self.db.add(initial_event)
                    self.db.flush()
                if commit:
                    self.db.commit()
                    self.db.refresh(incident_candidate)
                new_inc = incident_candidate
                break
            except IntegrityError as exc:
                orig_msg = str(getattr(exc, "orig", exc)).lower()
                if "incident_number" in orig_msg:
                    continue
                if "correlation_group_id" in orig_msg:
                    existing = self.incident_repo.get_by_correlation_group_id(correlation_group.id)
                    if existing:
                        return existing
                raise

        if not new_inc:
            existing = self.incident_repo.get_by_correlation_group_id(correlation_group.id)
            if existing:
                return existing
            raise RuntimeError(
                f"Failed to generate unique incident for correlation group {correlation_group.id} after {max_attempts} attempts."
            )

        return new_inc

    def update_status(self, identifier: str, update_req: IncidentStatusUpdateRequest) -> IncidentDetailResponse:
        """Validate and apply an incident status transition according to defined lifecycle policy."""
        self.ensure_default_seed()
        incident = None
        try:
            val_uuid = UUID(identifier)
            incident = self.incident_repo.get_by_id(val_uuid)
        except ValueError:
            pass

        if not incident:
            incident = self.incident_repo.get_by_number(identifier)

        if not incident:
            raise IncidentNotFoundError(f"Incident '{identifier}' was not found.")

        current_status_str = incident.status
        try:
            current_status = IncidentStatus(current_status_str)
        except ValueError:
            current_status = IncidentStatus.INVESTIGATING

        target_status = update_req.status

        # If already in the target status, idempotent return without creating duplicate timeline events
        if current_status == target_status:
            changed = False
            if update_req.commander_name and incident.commander_name != update_req.commander_name:
                incident.commander_name = update_req.commander_name
                changed = True
            if update_req.commander_role and incident.commander_role != update_req.commander_role:
                incident.commander_role = update_req.commander_role
                changed = True
            if changed:
                self.db.commit()
                self.db.refresh(incident)
            return self.get_incident_by_id_or_number(str(incident.id))

        # Validate transition against lifecycle matrix
        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            allowed_names = sorted([s.value for s in allowed])
            raise InvalidStatusTransitionError(
                f"Invalid status transition from '{current_status.value}' to '{target_status.value}'. "
                f"Allowed transitions from '{current_status.value}': {allowed_names}"
            )

        now_utc = datetime.now(timezone.utc)
        incident.status = target_status.value

        # Timestamp updates
        if target_status == IncidentStatus.MITIGATED and not incident.mitigated_at:
            incident.mitigated_at = now_utc
        elif target_status == IncidentStatus.RESOLVED and not incident.resolved_at:
            incident.resolved_at = now_utc

        # Commander updates
        if update_req.commander_name:
            incident.commander_name = update_req.commander_name
        if update_req.commander_role:
            incident.commander_role = update_req.commander_role

        # Persist timeline audit event
        desc = update_req.comment or f"Incident status transitioned from {current_status.value} to {target_status.value}."
        event = IncidentEvent(
            id=uuid.uuid4(),
            incident_id=incident.id,
            timestamp=now_utc,
            title=f"Status changed to {target_status.value}",
            event_type="human" if update_req.commander_name else "action",
            source=update_req.commander_name or "System Responder",
            description=desc,
            payload={
                "from_status": current_status.value,
                "to_status": target_status.value,
                "commander_name": incident.commander_name,
                "commander_role": incident.commander_role,
            },
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(incident)

        return self.get_incident_by_id_or_number(str(incident.id))

    def create_incident(self, project_id: UUID, req: IncidentCreateRequest) -> IncidentDetailResponse:
        """Create a manual incident using the defined request schema."""
        self.ensure_default_seed()

        if req.correlation_group_id is not None:
            corr_group = self.db.query(CorrelationGroup).filter_by(id=req.correlation_group_id).first()
            if not corr_group:
                raise CorrelationGroupNotFoundError(
                    f"Correlation group '{req.correlation_group_id}' was not found."
                )
            if corr_group.project_id != project_id:
                raise ProjectIsolationError(
                    f"Correlation group '{req.correlation_group_id}' belongs to a different project."
                )
            existing_inc = self.incident_repo.get_by_correlation_group_id(req.correlation_group_id)
            if existing_inc:
                raise CorrelationGroupAlreadyLinkedError(
                    f"Correlation group '{req.correlation_group_id}' is already linked to incident '{existing_inc.incident_number}'."
                )

        now_utc = datetime.now(timezone.utc)
        new_inc = None
        max_attempts = 5
        for attempt in range(max_attempts):
            inc_number = self.incident_repo.generate_next_incident_number()
            inc_id = uuid.uuid4()
            candidate = Incident(
                id=inc_id,
                project_id=project_id,
                correlation_group_id=req.correlation_group_id,
                incident_number=inc_number,
                title=req.title,
                severity=req.severity.value,
                status=IncidentStatus.DETECTED.value,
                started_at=now_utc,
                commander_name=req.commander_name or "Alex Chen",
                commander_role=req.commander_role or "Staff SRE",
                affected_services=req.affected_services,
                summary=req.summary,
                is_demo=False,
            )
            initial_event = IncidentEvent(
                id=uuid.uuid4(),
                incident_id=inc_id,
                timestamp=now_utc,
                title="Incident Created",
                event_type="human",
                source=candidate.commander_name,
                description=req.summary or f"Manual incident created with severity {req.severity.value}.",
                payload={},
            )
            try:
                with self.db.begin_nested():
                    self.db.add(candidate)
                    self.db.add(initial_event)
                    self.db.flush()
                self.db.commit()
                self.db.refresh(candidate)
                new_inc = candidate
                break
            except IntegrityError as exc:
                orig_msg = str(getattr(exc, "orig", exc)).lower()
                if "incident_number" in orig_msg:
                    continue
                raise

        if not new_inc:
            raise RuntimeError(f"Failed to generate unique incident after {max_attempts} attempts.")

        return self.get_incident_by_id_or_number(str(new_inc.id))

