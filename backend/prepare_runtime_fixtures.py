"""Prepares SQLite runtime database fixtures for Sprint 5.3 runtime verification."""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from uuid import uuid4

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.correlation import CorrelationGroup
from app.models.investigation import Investigation
from app.schemas.correlation import CorrelationEvaluationRequest, CorrelationConfig
from app.schemas.investigation import (
    InvestigationResult,
    TimelineEvidenceEvent,
    RootCauseEvidenceExplanation,
    EvidenceReference,
    UncertaintyGap,
    InvestigationStep,
    RemediationRecommendation,
    RemediationActionType,
    RiskLevel,
)
from app.services.project_service import ProjectService
from app.services.incident_service import IncidentService
from app.services.correlation.service import CorrelationService

def setup_runtime_db():
    print("Setting up runtime database tables...")
    # Clean recreate schema
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1. Ensure default seed (tenant, microservices, dependencies, INC-8492)
        proj_svc = ProjectService(db)
        proj = proj_svc.ensure_default_seed()
        print(f"Default project seeded: {proj.slug} ({proj.id})")

        inc_svc = IncidentService(db)
        inc_svc.ensure_default_seed()
        print("Default demo incidents seeded (including INC-8492).")

        # 2. Setup Services
        inv_svc = db.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
        order_svc = db.query(Service).filter_by(project_id=proj.id, slug="order-service").first()
        pay_svc = db.query(Service).filter_by(project_id=proj.id, slug="payment-service").first()
        auth_svc = db.query(Service).filter_by(project_id=proj.id, slug="auth-service").first()

        # 3. Create Group 1: Inventory -> Order Cascade
        t1 = datetime(2026, 11, 7, 14, 0, 0, tzinfo=timezone.utc)
        ev1 = AnomalyEvent(
            id=uuid4(),
            project_id=proj.id,
            service_id=inv_svc.id,
            metric_name="latency",
            observed_value=480.0,
            expected_baseline=40.0,
            deviation_pct=1100.0,
            severity="critical",
            detection_method="rolling_average",
            occurred_at=t1,
            status="open",
            explanation="Inventory query lock wait timeout on warehouse DB",
        )
        ev2 = AnomalyEvent(
            id=uuid4(),
            project_id=proj.id,
            service_id=order_svc.id,
            metric_name="latency",
            observed_value=920.0,
            expected_baseline=80.0,
            deviation_pct=1050.0,
            severity="high",
            detection_method="rolling_average",
            occurred_at=t1 + timedelta(seconds=25),
            status="open",
            explanation="Order service HTTP 504 timeouts to callers",
        )
        db.add_all([ev1, ev2])
        db.commit()

        corr_svc = CorrelationService(db)
        res1 = corr_svc.evaluate_and_persist(
            CorrelationEvaluationRequest(
                project_id=proj.id,
                start_time=t1 - timedelta(minutes=2),
                end_time=t1 + timedelta(minutes=2),
                config=CorrelationConfig(min_events_per_group=2),
            )
        )
        group1 = res1.groups[0]
        print(f"Group 1 created: {group1.id} (summary: {group1.summary})")

        # Persist a real Grounded Investigation for Group 1
        cand1 = group1.ranked_candidates[0]
        persisted_result = InvestigationResult(
            incident_summary="Inventory Service query lock contention caused high latency at 14:00:00 UTC, propagating downstream to Order Service within 25 seconds.",
            timeline=[
                TimelineEvidenceEvent(
                    timestamp=ev1.occurred_at,
                    event_id=ev1.id,
                    service_id=inv_svc.id,
                    service_name=inv_svc.name,
                    metric_name="latency",
                    observation="Observed latency spiked to 480.0ms (+1100% deviation) during warehouse DB lock contention.",
                    severity="critical",
                ),
                TimelineEvidenceEvent(
                    timestamp=ev2.occurred_at,
                    event_id=ev2.id,
                    service_id=order_svc.id,
                    service_name=order_svc.name,
                    metric_name="latency",
                    observation="Observed latency degraded to 920.0ms (+1050% deviation) while awaiting inventory stock confirmation.",
                    severity="high",
                ),
            ],
            root_cause_analysis=RootCauseEvidenceExplanation(
                candidate_id=cand1.service_id, # candidate id matches service in candidate
                service_id=inv_svc.id,
                service_name=inv_svc.name,
                explanation="Inventory Service is the initiating root cause node due to warehouse database lock starvation. Query wait times spiked to 480ms and cascaded to Order Service.",
                contributing_factors=[
                    "Warehouse database exclusive row lock held by reconciliation job",
                    "Missing read timeout on checkout inventory checks",
                ],
            ),
            evidence_references=[
                EvidenceReference(
                    source_record_type="anomaly_event",
                    source_id=ev1.id,
                    supported_field="observed_value",
                    summary_citation="Inventory Service latency 480.0ms at 14:00:00 UTC was first initiating event.",
                ),
                EvidenceReference(
                    source_record_type="anomaly_event",
                    source_id=ev2.id,
                    supported_field="observed_value",
                    summary_citation="Order Service latency 920.0ms at 14:00:25 UTC confirmed downstream cascade.",
                ),
            ],
            uncertainties_and_gaps=[
                UncertaintyGap(
                    category="unobserved_metric",
                    description="Database buffer pool hit ratio was not recorded during the 5-minute anomaly window.",
                    impact_on_confidence="Low: Latency and temporal precedence reliably identify Inventory Service as the cascade initiator.",
                ),
            ],
            prioritized_investigation_steps=[
                InvestigationStep(
                    step_number=1,
                    target_service=inv_svc.name,
                    action="Inspect active connections and lock wait times on warehouse inventory database.",
                    purpose="Confirm whether lock contention has cleared or if blocked transactions persist.",
                ),
                InvestigationStep(
                    step_number=2,
                    target_service=order_svc.name,
                    action="Verify circuit breaker state on downstream inventory calls.",
                    purpose="Ensure order traffic is recovering and error rate is normalized.",
                ),
            ],
            remediation_recommendations=[
                RemediationRecommendation(
                    title="Terminate Warehouse Reconciliation Lock and Restart Connection Pool",
                    action_type=RemediationActionType.RESTART,
                    target_service=inv_svc.name,
                    description="Terminate idle in transaction connections older than 5 minutes on warehouse DB and restart connection pooler.",
                    risk_level=RiskLevel.MEDIUM,
                    preconditions=[
                        "Ensure inventory replica is healthy and read-only traffic is diverted",
                        "Verify no batch imports are actively writing to product_inventory table",
                    ],
                    rollback_procedure="Revert connection pooler configuration and restore default timeout settings.",
                    requires_human_approval=True,
                    command_snippet=None,
                ),
            ],
        )

        inv_record = Investigation(
            id=uuid4(),
            correlation_group_id=group1.id,
            incident_id=None,
            provider="google-gemini",
            model_name="gemini-3.8-flash",
            prompt_version="v1.0",
            schema_version="v1.0",
            status="COMPLETED",
            evidence_hash="sha256:runtime_test_hash_verified_grounded_12345",
            investigation_json=persisted_result.model_dump(mode="json"),
            prompt_tokens=1450,
            completion_tokens=680,
            total_tokens=2130,
            latency_ms=2150,
            error_message=None,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            completed_at=datetime.now(timezone.utc),
            is_demo=False,
        )
        db.add(inv_record)
        db.commit()
        print(f"Persisted investigation created for Group 1: {inv_record.id}")

        # 4. Create Group 2: API Gateway -> Auth Service Cascade (WITHOUT any existing investigation)
        gw_svc = db.query(Service).filter_by(project_id=proj.id, slug="api-gateway").first()
        t2 = datetime(2026, 11, 7, 15, 30, 0, tzinfo=timezone.utc)
        ev3 = AnomalyEvent(
            id=uuid4(),
            project_id=proj.id,
            service_id=auth_svc.id,
            metric_name="latency",
            observed_value=600.0,
            expected_baseline=30.0,
            deviation_pct=1900.0,
            severity="critical",
            detection_method="rolling_average",
            occurred_at=t2,
            status="open",
            explanation="Auth Service JWT signing key verification latency",
        )
        ev4 = AnomalyEvent(
            id=uuid4(),
            project_id=proj.id,
            service_id=gw_svc.id,
            metric_name="latency",
            observed_value=1200.0,
            expected_baseline=60.0,
            deviation_pct=1900.0,
            severity="critical",
            detection_method="rolling_average",
            occurred_at=t2 + timedelta(seconds=15),
            status="open",
            explanation="API Gateway ingress route blocked awaiting auth verification",
        )
        db.add_all([ev3, ev4])
        db.commit()

        res2 = corr_svc.evaluate_and_persist(
            CorrelationEvaluationRequest(
                project_id=proj.id,
                start_time=t2 - timedelta(minutes=2),
                end_time=t2 + timedelta(minutes=2),
                config=CorrelationConfig(min_events_per_group=2),
            )
        )
        group2 = res2.groups[0]
        print(f"Group 2 created (NO investigation): {group2.id} (summary: {group2.summary})")

        # 5. Create Group 3: Order -> Payment Cascade with FAILED Investigation
        t3 = datetime(2026, 11, 7, 16, 0, 0, tzinfo=timezone.utc)
        ev5 = AnomalyEvent(
            id=uuid4(),
            project_id=proj.id,
            service_id=pay_svc.id,
            metric_name="latency",
            observed_value=750.0,
            expected_baseline=50.0,
            deviation_pct=1400.0,
            severity="critical",
            detection_method="rolling_average",
            occurred_at=t3,
            status="open",
            explanation="Payment Gateway connection timeout spike",
        )
        ev6 = AnomalyEvent(
            id=uuid4(),
            project_id=proj.id,
            service_id=order_svc.id,
            metric_name="error_rate",
            observed_value=0.28,
            expected_baseline=0.01,
            deviation_pct=2700.0,
            severity="critical",
            detection_method="rolling_average",
            occurred_at=t3 + timedelta(seconds=20),
            status="open",
            explanation="Order checkout failure rate increased due to payment gateway timeouts",
        )
        db.add_all([ev5, ev6])
        db.commit()

        res3 = corr_svc.evaluate_and_persist(
            CorrelationEvaluationRequest(
                project_id=proj.id,
                start_time=t3 - timedelta(minutes=2),
                end_time=t3 + timedelta(minutes=2),
                config=CorrelationConfig(min_events_per_group=2),
            )
        )
        group3 = res3.groups[0]
        inv_failed = Investigation(
            id=uuid4(),
            correlation_group_id=group3.id,
            incident_id=None,
            provider="google-gemini",
            model_name="gemini-2.0-flash",
            prompt_version="v1.0",
            schema_version="v1.0",
            status="FAILED",
            evidence_hash=None,
            investigation_json=None,
            error_message="Gemini quota exceeded or rate limit reached (HTTP 429). Check provider quota.",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            completed_at=datetime.now(timezone.utc) - timedelta(minutes=4),
            is_demo=False,
        )
        db.add(inv_failed)
        db.commit()
        print(f"Group 3 created (FAILED investigation): {group3.id} (inv: {inv_failed.id})")

        # 6. Create Group 4: Auth -> Gateway Cascade with RUNNING Investigation
        t4 = datetime(2026, 11, 7, 16, 30, 0, tzinfo=timezone.utc)
        ev7 = AnomalyEvent(
            id=uuid4(),
            project_id=proj.id,
            service_id=auth_svc.id,
            metric_name="cpu_utilization",
            observed_value=96.5,
            expected_baseline=35.0,
            deviation_pct=175.0,
            severity="high",
            detection_method="rolling_average",
            occurred_at=t4,
            status="open",
            explanation="Auth Service bcrypt hashing loop CPU saturation",
        )
        ev8 = AnomalyEvent(
            id=uuid4(),
            project_id=proj.id,
            service_id=gw_svc.id,
            metric_name="latency",
            observed_value=850.0,
            expected_baseline=50.0,
            deviation_pct=1600.0,
            severity="critical",
            detection_method="rolling_average",
            occurred_at=t4 + timedelta(seconds=10),
            status="open",
            explanation="API Gateway ingress backlog due to auth CPU bottleneck",
        )
        db.add_all([ev7, ev8])
        db.commit()

        res4 = corr_svc.evaluate_and_persist(
            CorrelationEvaluationRequest(
                project_id=proj.id,
                start_time=t4 - timedelta(minutes=2),
                end_time=t4 + timedelta(minutes=2),
                config=CorrelationConfig(min_events_per_group=2),
            )
        )
        group4 = res4.groups[0]
        inv_running = Investigation(
            id=uuid4(),
            correlation_group_id=group4.id,
            incident_id=None,
            provider="google-gemini",
            model_name="gemini-2.0-flash",
            prompt_version="v1.0",
            schema_version="v1.0",
            status="RUNNING",
            evidence_hash=None,
            investigation_json=None,
            error_message=None,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=20),
            completed_at=None,
            is_demo=False,
        )
        db.add(inv_running)
        db.commit()
        print(f"Group 4 created (RUNNING investigation): {group4.id} (inv: {inv_running.id})")

        fixtures = {
            "project_id": str(proj.id),
            "group_completed_id": str(group1.id),
            "investigation_completed_id": str(inv_record.id),
            "group_no_inv_id": str(group2.id),
            "group_failed_id": str(group3.id),
            "investigation_failed_id": str(inv_failed.id),
            "group_running_id": str(group4.id),
            "investigation_running_id": str(inv_running.id),
        }
        
        import json
        fixtures_path = backend_dir / "runtime_fixtures.json"
        with open(fixtures_path, "w", encoding="utf-8") as f:
            json.dump(fixtures, f, indent=2)
        print(f"Wrote fixture metadata to {fixtures_path}")

        print("Runtime database fixture setup complete!")
        return fixtures

    finally:
        db.close()

if __name__ == "__main__":
    setup_runtime_db()
