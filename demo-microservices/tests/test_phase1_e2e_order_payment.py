"""Phase 1 Multi-Signal E2E Integration Test:
Order -> Inventory & Payment traffic + Payment Latency Fault -> TraceMind Ingestion ->
Persisted Metrics, Anomaly Events, Correlated Logs, and Parent-Child Distributed Trace Waterfall.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
import pytest
import httpx
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

backend_path = Path(__file__).resolve().parent.parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.main import app as tracemind_app
from app.db.base import Base
from app.db.session import get_db
from app.models.telemetry import ApplicationLog, MetricSample, TraceSpan
from app.models.anomaly import AnomalyEvent
from app.services.project_service import ProjectService
from app.services.anomaly.registry import get_anomaly_registry

from common.models import FaultConfig
from common.tracing import TRACE_ID_HEADER
from services.order_service import main as order_main
from services.payment_service import main as pay_main
from services.inventory_service import main as inv_main
from services.inventory_service.store import inventory_store
from simulator.scenarios import ScenarioRunner


@pytest.mark.asyncio
async def test_phase1_order_to_payment_multi_signal_observability_e2e():
    """Verify normal warmup + payment-latency fault persists raw metrics, triggers anomaly,
    and correlates structured logs and parent-child span waterfall under the same trace_id."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_phase1_e2e.db").replace("\\", "/")
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)
    get_anomaly_registry().reset_all()

    db = TestingSessionLocal()
    seeded_project = ProjectService(db).ensure_default_seed()
    project_id = str(seeded_project.id)
    db.close()

    def override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    tracemind_app.dependency_overrides[get_db] = override_get_db

    inventory_store.reset()
    inv_main.current_fault = FaultConfig()
    pay_main.current_fault = FaultConfig()
    order_main.current_fault = FaultConfig()
    order_main.orders_db.clear()

    tm_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tracemind_app),
        base_url="http://tracemind-test/api/v1",
    )
    inv_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=inv_main.app), base_url="http://inventory-test")
    pay_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=pay_main.app), base_url="http://payment-test")
    order_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=order_main.app), base_url="http://order-test")

    order_main.clients._inventory_client = inv_client
    order_main.clients._payment_client = pay_client

    for svc_mod in (order_main, pay_main, inv_main):
        svc_mod.telemetry.enabled = True
        svc_mod.telemetry.base_url = "http://tracemind-test/api/v1"
        svc_mod.telemetry._configured_project_id = project_id
        svc_mod.telemetry._resolved_project_id = seeded_project.id
        svc_mod.telemetry._http_client = tm_client
        svc_mod.telemetry._owns_http_client = False
        svc_mod.telemetry._last_timestamps.clear()
        await svc_mod.telemetry.start()

    runner = ScenarioRunner(
        order_client=order_client,
        payment_client=pay_client,
        inventory_client=inv_client,
        tracemind_client=tm_client,
    )

    anomaly_trace_id = None
    try:
        # 1. Warmup traffic to build rolling baseline for latency/error_rate/request_rate
        warmup = await runner.run_normal_traffic(count=8, interval_sec=0.02)
        assert warmup.confirmed_count == 8

        # 2. Inject Payment Service +650ms latency spike and execute single traceable order
        await runner.run_payment_latency_spike(
            delay_ms=650.0,
            requests=1,
            settle_delay_sec=0.01,
            trigger_correlation=False,
        )
        direct_resp = await order_client.post(
            "/orders",
            json={
                "customer_id": "cust-phase1-e2e",
                "items": [{"sku": "SKU-LAPTOP-01", "quantity": 1, "unit_price": 1299.99}],
                "payment_method": "card",
            },
        )
        assert direct_resp.status_code == 201
        anomaly_trace_id = direct_resp.headers.get(TRACE_ID_HEADER)
        assert anomaly_trace_id

        # 3. Drain all queued metrics, logs, and spans into TraceMind SQLite DB
        await asyncio.gather(
            order_main.telemetry.stop(timeout=8.0),
            pay_main.telemetry.stop(timeout=8.0),
            inv_main.telemetry.stop(timeout=8.0),
        )

        # 4. Query TraceMind APIs directly to prove end-to-end persistence & correlation
        traces_resp = await tm_client.get(f"/traces?project_id={project_id}&min_duration_ms=500")
        assert traces_resp.status_code == 200
        traces_data = traces_resp.json()
        trace_ids = [item["id"] for item in traces_data["items"]]
        assert anomaly_trace_id in trace_ids

        detail_resp = await tm_client.get(f"/traces/{anomaly_trace_id}?project_id={project_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["durationMs"] >= 600.0
        span_services = {s["service_slug"] for s in detail["spans"]}
        assert {"order-service", "inventory-service", "payment-service"}.issubset(span_services)

        bottlenecks = [s for s in detail["spans"] if s["isBottleneck"]]
        assert len(bottlenecks) >= 1
        assert any(s["service_slug"] == "payment-service" for s in bottlenecks)

        logs_resp = await tm_client.get(f"/logs?project_id={project_id}&trace_id={anomaly_trace_id}")
        assert logs_resp.status_code == 200
        logs_data = logs_resp.json()
        assert logs_data["total"] >= 3
        log_services = {item["service_slug"] for item in logs_data["items"]}
        assert {"order-service", "payment-service", "inventory-service"}.issubset(log_services)

        metrics_resp = await tm_client.get(f"/telemetry/metrics?project_id={project_id}&limit=100")
        assert metrics_resp.status_code == 200
        metrics_data = metrics_resp.json()
        metric_names = {m["metric_name"] for m in metrics_data["items"]}
        assert {"latency", "error_rate", "request_rate", "request_count"}.issubset(metric_names)

        # 5. Inspect DB directly for AnomalyEvent + correlated trace_id
        verify_db = TestingSessionLocal()
        try:
            assert verify_db.query(MetricSample).count() > 0
            assert verify_db.query(ApplicationLog).filter(ApplicationLog.trace_id == anomaly_trace_id).count() >= 3
            assert verify_db.query(TraceSpan).filter(TraceSpan.trace_id == anomaly_trace_id).count() >= 6
            anomaly_count = verify_db.query(AnomalyEvent).filter(AnomalyEvent.metric_name == "latency").count()
            assert anomaly_count >= 1
        finally:
            verify_db.close()

    finally:
        pay_main.current_fault = FaultConfig()
        inv_main.current_fault = FaultConfig()
        order_main.current_fault = FaultConfig()
        await tm_client.aclose()
        await order_client.aclose()
        await pay_client.aclose()
        await inv_client.aclose()
        tracemind_app.dependency_overrides.clear()
        get_anomaly_registry().reset_all()
        engine.dispose()
        try:
            os.remove(db_path)
            os.rmdir(tmpdir)
        except OSError:
            pass
