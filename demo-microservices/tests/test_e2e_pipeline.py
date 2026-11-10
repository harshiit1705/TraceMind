"""Full End-to-End Integration Test:

Real Business Requests -> Telemetry Reporting -> Statistical Baseline -> Anomaly Detection ->
Cross-Service Correlation -> Auto-Incident Creation -> Evidence-Grounded Investigation.
"""

import os
import sys
import tempfile
from pathlib import Path
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend is importable for setting up isolated TraceMind test app
backend_path = Path(__file__).resolve().parent.parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.main import app as tracemind_app
from app.db.base import Base
from app.db.session import get_db
from app.services.project_service import ProjectService
from app.services.anomaly.registry import get_anomaly_registry
from app.services.investigation.provider import InvestigationProvider, InvestigationProviderResult
from app.schemas.investigation import (
    EvidencePackage,
    InvestigationResult,
    RootCauseEvidenceExplanation,
    TimelineEvidenceEvent,
    EvidenceReference,
    InvestigationStep,
    RemediationRecommendation,
    RemediationActionType,
    RiskLevel,
)

from common.models import FaultConfig
from services.order_service import main as order_main
from services.payment_service import main as pay_main
from services.inventory_service import main as inv_main
from services.inventory_service.store import inventory_store
from simulator.scenarios import ScenarioRunner


class GroundedTestInvestigationProvider(InvestigationProvider):
    """Synthesizes an investigation strictly grounded in the real EvidencePackage emitted by demo traffic."""

    async def generate_investigation(self, evidence: EvidencePackage) -> InvestigationProviderResult:
        top_cand = evidence.ranked_candidates[0]
        first_ev = evidence.participating_events[0]

        timeline = [
            TimelineEvidenceEvent(
                timestamp=ev.occurred_at,
                event_id=ev.event_id,
                service_id=ev.service_id,
                service_name=ev.service_name,
                metric_name=ev.metric_name,
                observation=f"Observed {ev.observed_value:.1f} vs baseline {ev.expected_baseline:.1f}",
                severity=ev.severity,
            )
            for ev in evidence.participating_events[:3]
        ]

        result = InvestigationResult(
            incident_summary=(
                f"Detected cascading latency surge originating in {top_cand.service_name} "
                f"and propagating downstream to dependent checkout services."
            ),
            root_cause_analysis=RootCauseEvidenceExplanation(
                candidate_id=top_cand.candidate_id,
                service_id=top_cand.service_id,
                service_name=top_cand.service_name,
                explanation=(
                    f"{top_cand.service_name} exhibited critical latency spike "
                    f"({first_ev.observed_value:.1f}ms vs baseline {first_ev.expected_baseline:.1f}ms) "
                    f"preceding downstream degradation."
                ),
                contributing_factors=["Upstream warehouse lock contention", "Synchronous downstream blocking"],
            ),
            timeline=timeline,
            evidence_references=[
                EvidenceReference(
                    source_record_type="anomaly_event",
                    source_id=first_ev.event_id,
                    supported_field="observed_value",
                    summary_citation=f"Latency measured at {first_ev.observed_value:.1f}ms",
                )
            ],
            uncertainties_and_gaps=[],
            prioritized_investigation_steps=[
                InvestigationStep(
                    step_number=1,
                    target_service=top_cand.service_name,
                    action="Inspect active lock waits and slow queries on stock catalog",
                    purpose="Confirm root cause of latency escalation",
                )
            ],
            remediation_recommendations=[
                RemediationRecommendation(
                    title="Enable query timeout and connection pooling limits",
                    action_type=RemediationActionType.CONFIGURATION,
                    target_service=top_cand.service_name,
                    description="Enforce strict statement timeout on warehouse stock queries to avoid cascading thread exhaustion.",
                    risk_level=RiskLevel.LOW,
                    preconditions=["Verify read-replica availability"],
                    rollback_procedure="Revert timeout configuration parameter if false aborts increase",
                    requires_human_approval=True,
                )
            ],
        )

        return InvestigationProviderResult(
            result=result,
            provider="google-gemini-test-mock",
            model_name="gemini-2.0-flash",
            prompt_tokens=150,
            completion_tokens=200,
            total_tokens=350,
            latency_ms=420,
        )


@pytest.fixture
def isolated_e2e_environment(monkeypatch):
    """Spins up an isolated TraceMind SQLite database and wires all 3 demo services + TraceMind."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_e2e_pipeline.db").replace("\\", "/")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)
    get_anomaly_registry().reset_all()

    db = TestingSessionLocal()
    ProjectService(db).ensure_default_seed()
    db.close()

    def override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    tracemind_app.dependency_overrides[get_db] = override_get_db

    # Reset demo services state
    inventory_store.reset()
    inv_main.current_fault = FaultConfig()
    pay_main.current_fault = FaultConfig()
    order_main.current_fault = FaultConfig()
    order_main.orders_db.clear()

    # Create ASGI clients
    tm_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tracemind_app),
        base_url="http://tracemind-test/api/v1",
    )
    inv_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=inv_main.app),
        base_url="http://inventory-test",
    )
    pay_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=pay_main.app),
        base_url="http://payment-test",
    )
    order_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=order_main.app),
        base_url="http://order-test",
    )

    # Wire Order Service downstream
    order_main.clients._inventory_client = inv_client
    order_main.clients._payment_client = pay_client

    # Wire TelemetryClients of all 3 services directly to TraceMind ASGI client
    for svc_mod in (order_main, pay_main, inv_main):
        svc_mod.telemetry.enabled = True
        svc_mod.telemetry._http_client = tm_client
        svc_mod.telemetry.base_url = "http://tracemind-test/api/v1"
        svc_mod.telemetry._resolved_project_id = None
        svc_mod.telemetry._last_timestamps.clear()

    runner = ScenarioRunner(
        order_client=order_client,
        payment_client=pay_client,
        inventory_client=inv_client,
        tracemind_client=tm_client,
    )

    yield runner, tm_client, order_client, pay_client, inv_client, engine

    tracemind_app.dependency_overrides.clear()
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_complete_e2e_workflow_traffic_to_investigation(isolated_e2e_environment, monkeypatch):
    """Verify full TraceMind lifecycle driven strictly by real demo microservices requests."""
    runner, tm_client, order_client, pay_client, inv_client, _ = isolated_e2e_environment

    # Inject grounded test provider into InvestigationService
    from app.api.v1 import investigations as inv_api
    monkeypatch.setattr(
        "app.services.investigation.gemini_provider.GeminiInvestigationProvider.generate_investigation",
        GroundedTestInvestigationProvider().generate_investigation,
    )

    # Start background telemetry queues
    await order_main.telemetry.start()
    await pay_main.telemetry.start()
    await inv_main.telemetry.start()

    try:
        # 1. Warmup: 5 normal orders -> establishes statistical baselines
        norm_summary = await runner.run_normal_traffic(count=5, interval_sec=0.05)
        assert norm_summary.confirmed_count == 5
        assert norm_summary.failed_count == 0

        # Wait briefly for telemetry queues to flush warmup baselines
        import asyncio
        await asyncio.sleep(0.5)

        # 2. Fault Injection: Inventory Latency Spike (+650ms) -> Triggers real anomalies + correlation
        inv_result = await runner.run_inventory_latency_spike(
            delay_ms=650.0,
            requests=3,
            settle_delay_sec=0.5,
            trigger_correlation=True,
            reset_prior=False,
        )
        assert inv_result["traffic_summary"]["confirmed"] == 3
        assert inv_result["traffic_summary"]["avg_latency_ms"] >= 650.0

        corr = inv_result["correlation_result"]
        assert corr is not None
        assert corr["correlation_groups_count"] >= 1
        group = corr["groups"][0]
        group_id = group["id"]

        # Verify Inventory Service is ranked #1 root cause
        top_cand = group["ranked_candidates"][0]
        assert top_cand["service_slug"] == "inventory-service"
        assert top_cand["is_probable_root_cause"] is True

        # 3. Verify Automatic Incident Creation in TraceMind
        inc_resp = await tm_client.get("/incidents")
        assert inc_resp.status_code == 200
        incidents = inc_resp.json()["items"]
        linked_inc = next((i for i in incidents if i.get("correlation_group_id") == group_id), None)
        assert linked_inc is not None
        assert linked_inc["status"] == "DETECTED"

        # 4. Trigger Evidence-Grounded Investigation on the Real Correlation Group
        gen_resp = await tm_client.post(
            "/investigations/generate",
            json={"correlation_group_id": group_id},
        )
        assert gen_resp.status_code == 200
        inv_data = gen_resp.json()
        assert inv_data["status"] == "COMPLETED"
        assert "Inventory Service" in inv_data["investigation_json"]["root_cause_analysis"]["service_name"]

        # 5. Verify Investigation is retrievable directly from Incident Investigation Endpoint
        inc_inv_resp = await tm_client.get(f"/incidents/{linked_inc['id']}/investigation")
        assert inc_inv_resp.status_code == 200
        assert inc_inv_resp.json()["id"] == inv_data["id"]

    finally:
        await order_main.telemetry.stop()
        await pay_main.telemetry.stop()
        await inv_main.telemetry.stop()
        order_main.telemetry._http_client = None
        pay_main.telemetry._http_client = None
        inv_main.telemetry._http_client = None
        await tm_client.aclose()
        await order_client.aclose()
        await pay_client.aclose()
        await inv_client.aclose()
