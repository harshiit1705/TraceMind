import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent
from app.models.investigation import Investigation
from app.models.finding import Finding
from app.models.recommendation import Recommendation
from app.repositories.incident_repository import IncidentRepository
from app.repositories.investigation_repository import InvestigationRepository
from app.services.project_service import ProjectService
from app.services.demo.evidence_provider import get_evidence_provider
from app.schemas.incident import (
    IncidentResponse,
    IncidentDetailResponse,
    IncidentEventResponse,
    TimelineResponse,
)
from app.schemas.evidence import EvidenceResponse, EvidenceListResponse
from app.schemas.investigation import InvestigationDetailResponse


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

