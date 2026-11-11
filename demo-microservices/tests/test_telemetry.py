"""Unit and integration tests for demo-microservices telemetry client."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4
import pytest
import httpx

from common.telemetry import TelemetryClient
from common.models import OrderCreateRequest, OrderItem, OrderStatus


@pytest.mark.asyncio
async def test_telemetry_client_initialization():
    """Verify TelemetryClient initializes with default bounded settings."""
    client = TelemetryClient(service_identifier="order-service")
    assert client.service_identifier == "order-service"
    assert client.timeout == 2.0
    assert client.max_retries == 1
    assert client.enabled is True


@pytest.mark.asyncio
async def test_telemetry_failure_isolation_on_unreachable_host():
    """Verify telemetry failure does NOT raise an exception when TraceMind is unreachable."""
    client = TelemetryClient(
        service_identifier="order-service",
        base_url="http://127.0.0.1:59999/api/v1",  # Non-existent port
        project_id=str(uuid4()),
        timeout=0.2,
        max_retries=0,
    )
    # Direct transmission must return False and not raise any exception
    success = await client.send_measurement_direct(
        metric_name="latency",
        observed_value=45.5,
    )
    assert success is False


@pytest.mark.asyncio
async def test_telemetry_background_queue_and_drain():
    """Verify background queue non-blocking queuing and clean stop."""
    client = TelemetryClient(
        service_identifier="payment-service",
        base_url="http://127.0.0.1:59999/api/v1",
        project_id=str(uuid4()),
        timeout=0.1,
    )
    await client.start()
    assert client._started is True

    # Record multiple metrics (non-blocking)
    client.record_latency(55.2)
    client.record_error_rate(0.0)
    client.record_request_rate(12.5)

    # Allow worker to attempt dispatch
    await asyncio.sleep(0.3)
    await client.stop()
    assert client._started is False


@pytest.mark.asyncio
async def test_telemetry_payload_schema_compatibility_with_tracemind():
    """Verify that TelemetryClient generates payloads strictly compliant with TraceMind /anomalies/evaluate."""
    # We mount TraceMind's real FastAPI app in-memory using httpx.ASGITransport to verify schema
    import sys
    from pathlib import Path
    backend_path = Path(__file__).resolve().parent.parent.parent / "backend"
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))

    from app.main import app
    from app.db.session import SessionLocal
    from app.models.project import Project

    db = SessionLocal()
    try:
        project = db.query(Project).first()
        assert project is not None, "Project seed required"
        project_id = project.id
    finally:
        db.close()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver/api/v1") as test_client:
        telemetry = TelemetryClient(
            service_identifier="order-service",
            base_url="http://testserver/api/v1",
            project_id=str(project_id),
        )
        telemetry._http_client = test_client

        # Send warmup measurement 1
        now = datetime.now(timezone.utc)
        res1 = await telemetry.send_measurement_direct(
            metric_name="latency",
            observed_value=50.0,
            timestamp=now,
        )
        assert res1 is True

        # Send warmup measurement 2 with monotonic timestamp
        from datetime import timedelta
        res2 = await telemetry.send_measurement_direct(
            metric_name="latency",
            observed_value=52.0,
            timestamp=now + timedelta(seconds=1),
        )
        assert res2 is True

        # Send error_rate metric
        res3 = await telemetry.send_measurement_direct(
            metric_name="error_rate",
            observed_value=0.0,
            timestamp=now + timedelta(seconds=2),
        )
        assert res3 is True


@pytest.mark.asyncio
async def test_telemetry_project_auto_discovery():
    """Verify TelemetryClient can auto-discover project_id from TraceMind /projects endpoint."""
    import sys
    from pathlib import Path
    backend_path = Path(__file__).resolve().parent.parent.parent / "backend"
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))

    from app.main import app
    from app.db.session import SessionLocal
    from app.models.project import Project

    db = SessionLocal()
    try:
        project = db.query(Project).filter_by(slug="core-ecommerce").first()
        assert project is not None
        expected_project_id = project.id
    finally:
        db.close()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver/api/v1") as test_client:
        # Create client without explicit project_id
        telemetry = TelemetryClient(
            service_identifier="order-service",
            base_url="http://testserver/api/v1",
            project_id=None,
        )
        telemetry._http_client = test_client

        discovered_id = await telemetry.ensure_project_id()
        assert discovered_id == expected_project_id
        assert telemetry._resolved_project_id == expected_project_id


@pytest.mark.asyncio
async def test_project_discovery_fail_closed_on_missing_or_mismatched_slug(caplog):
    """Verify TelemetryClient and ScenarioRunner fail closed when project slug does not match."""
    from simulator.scenarios import ScenarioRunner

    wrong_project_id = str(uuid4())

    async def handler_mismatched(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json=[{"id": wrong_project_id, "slug": "wrong-project"}])
        return httpx.Response(404)

    async def handler_empty(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    # 1. Mismatched slug in TelemetryClient
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler_mismatched),
        base_url="http://mock-tm/api/v1",
    ) as mismatch_client:
        telemetry = TelemetryClient(
            service_identifier="order-service",
            base_url="http://mock-tm/api/v1",
            project_id=None,
            project_slug="core-ecommerce",
        )
        telemetry._http_client = mismatch_client

        resolved = await telemetry.ensure_project_id()
        assert resolved is None
        assert telemetry._resolved_project_id is None

        # Attempt direct send -> must fail closed (return False, not send to wrong project)
        sent = await telemetry.send_measurement_direct("latency", 42.0)
        assert sent is False

        # Mismatched slug in ScenarioRunner
        runner = ScenarioRunner(
            tracemind_url="http://mock-tm/api/v1",
            project_slug="core-ecommerce",
            tracemind_client=mismatch_client,
        )
        runner_proj = await runner.resolve_project_id()
        assert runner_proj is None
        corr_res = await runner.trigger_correlation_evaluation()
        assert corr_res is None

    # 2. Empty projects list
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler_empty),
        base_url="http://mock-tm/api/v1",
    ) as empty_client:
        telemetry_empty = TelemetryClient(
            service_identifier="order-service",
            base_url="http://mock-tm/api/v1",
            project_slug="core-ecommerce",
        )
        telemetry_empty._http_client = empty_client
        assert await telemetry_empty.ensure_project_id() is None

    # 3. Invalid configured project_id UUID
    telemetry_bad_uuid = TelemetryClient(
        service_identifier="order-service",
        project_id="not-a-valid-uuid",
    )
    assert await telemetry_bad_uuid.ensure_project_id() is None


@pytest.mark.asyncio
async def test_telemetry_queue_max_size_respected():
    """Verify queue_max_size constructor argument bounds the internal queue."""
    client = TelemetryClient(
        service_identifier="order-service",
        project_id=str(uuid4()),
        queue_max_size=2,
        enabled=True,
    )
    # Prevent worker from popping items during enqueue check by using a hanging transport or checking before yield
    blocker = asyncio.Event()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await blocker.wait()
        return httpx.Response(200, json={"is_anomaly": False})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(slow_handler),
        base_url="http://mock-tm/api/v1",
    ) as mock_client:
        client._http_client = mock_client
        await client.start()
        assert client._queue is not None
        assert client._queue.maxsize == 2

        # Enqueue 2 items (fills capacity 2 before worker yields)
        ok1 = client.record_measurement("latency", 10.0)
        ok2 = client.record_measurement("latency", 20.0)
        # 3rd item exceeds maxsize=2 and must be rejected cleanly
        ok3 = client.record_measurement("latency", 30.0)

        assert ok1 is True
        assert ok2 is True
        assert ok3 is False

        blocker.set()
        await client.stop(timeout=1.0)


@pytest.mark.asyncio
async def test_telemetry_graceful_shutdown_drains_queued_measurements_before_stop():
    """Verify queued measurements are delivered during stop(), new items rejected, and clients managed safely."""
    delivered_payloads = []

    async def recording_handler(request: httpx.Request) -> httpx.Response:
        # Simulate minor network delay so items remain queued when stop() is called immediately
        await asyncio.sleep(0.03)
        import json
        body = json.loads(request.content.decode("utf-8"))
        delivered_payloads.append(body)
        return httpx.Response(200, json={"is_anomaly": False, "detection_status": "NORMAL"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(recording_handler),
        base_url="http://mock-tm/api/v1",
    ) as mock_client:
        telemetry = TelemetryClient(
            service_identifier="inventory-service",
            base_url="http://mock-tm/api/v1",
            project_id=str(uuid4()),
            aggregation_interval_seconds=10.0,
        )
        telemetry._http_client = mock_client
        telemetry._owns_http_client = False

        await telemetry.start()
        # Queue 3 latency measurements and immediately stop() without waiting
        assert telemetry.record_latency(11.0) is True
        assert telemetry.record_latency(12.0) is True
        assert telemetry.record_latency(13.0) is True

        await telemetry.stop(timeout=3.0)

        # Verify ALL 3 queued measurements were actually delivered before stop() returned!
        delivered_samples = [s for body in delivered_payloads for s in body.get("samples", [])]
        assert len(delivered_samples) == 3
        assert [s["value"] for s in delivered_samples] == [11.0, 12.0, 13.0]

        # Verify new measurements are rejected after stop()
        assert telemetry.record_latency(14.0) is False
        delivered_samples_after = [s for body in delivered_payloads for s in body.get("samples", [])]
        assert len(delivered_samples_after) == 3

        # Verify injected HTTP client was NOT closed by stop()
        assert mock_client.is_closed is False

        # Verify repeated stop() is safe and idempotent
        await telemetry.stop(timeout=1.0)


@pytest.mark.asyncio
async def test_telemetry_shutdown_timeout_discards_and_logs_remaining(caplog):
    """Verify stop() respects bounded timeout when backend hangs and logs discarded count."""
    hang_event = asyncio.Event()

    async def hanging_handler(request: httpx.Request) -> httpx.Response:
        await hang_event.wait()
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(hanging_handler),
        base_url="http://mock-tm/api/v1",
    ) as mock_client:
        telemetry = TelemetryClient(
            service_identifier="payment-service",
            base_url="http://mock-tm/api/v1",
            project_id=str(uuid4()),
            timeout=5.0,
        )
        telemetry._http_client = mock_client

        await telemetry.start()
        telemetry.record_latency(10.0)
        telemetry.record_latency(20.0)
        telemetry.record_latency(30.0)
        # Allow worker to pick up the first item and block in hanging_handler
        await asyncio.sleep(0.05)

        caplog.clear()
        await telemetry.stop(timeout=0.15)
        hang_event.set()

        assert telemetry._started is False
        assert any("shutdown timeout" in rec.message.lower() and "discarded" in rec.message.lower() for rec in caplog.records)


@pytest.mark.asyncio
async def test_telemetry_repeated_start_stop_cycles_and_owned_client_cleanup():
    """Verify repeated start/stop cycles work cleanly and owned HTTP clients are closed on stop."""
    telemetry = TelemetryClient(
        service_identifier="order-service",
        project_id=str(uuid4()),
        enabled=True,
    )
    # Cycle 1
    await telemetry.start()
    owned_client_1 = telemetry._http_client
    assert owned_client_1 is not None
    assert telemetry._owns_http_client is True
    await telemetry.stop()
    assert owned_client_1.is_closed is True
    assert telemetry._http_client is None

    # Cycle 2
    await telemetry.start()
    owned_client_2 = telemetry._http_client
    assert owned_client_2 is not None and owned_client_2 is not owned_client_1
    await telemetry.stop()
    assert owned_client_2.is_closed is True


@pytest.mark.asyncio
async def test_metric_window_aggregation_error_rate_and_request_rate():
    """Verify bounded-window aggregation computes accurate error_rate (%) and request_rate (rps),
    while preserving individual latency emissions."""
    emitted = []

    async def capture_handler(request: httpx.Request) -> httpx.Response:
        import json
        emitted.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"is_anomaly": False, "detection_status": "NORMAL"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(capture_handler),
        base_url="http://mock-tm/api/v1",
    ) as mock_client:
        telemetry = TelemetryClient(
            service_identifier="order-service",
            base_url="http://mock-tm/api/v1",
            project_id=str(uuid4()),
            aggregation_interval_seconds=60.0,  # controlled flush manually & on stop
        )
        telemetry._http_client = mock_client
        await telemetry.start()

        # Empty window flush emits nothing
        assert telemetry.flush_window() is None

        # Zero / negative elapsed window must avoid division by zero and return None when not stopping
        import time as _time
        t_start = _time.monotonic() - 10.0
        telemetry._window_start_monotonic = t_start
        telemetry.record_request(latency_ms=40.0, is_error=False)
        telemetry.record_request(latency_ms=45.0, is_error=False)
        telemetry.record_request(latency_ms=50.0, is_error=True)
        telemetry.record_request(latency_ms=55.0, is_error=False)
        telemetry.record_request(latency_ms=60.0, is_error=True)

        assert telemetry.flush_window(now_monotonic=t_start) is None

        # Flush window at t_start + 2.0s -> 2/5 = 40.0% error_rate, 5/2.0 = 2.5 rps
        window_res = telemetry.flush_window(now_monotonic=t_start + 2.0)
        assert window_res == (40.0, 2.5)

        # Record 1 more request to test partial final window flush during stop() (8s elapsed from t_start+2.0)
        telemetry.record_request(latency_ms=70.0, is_error=False)

        await telemetry.stop(timeout=3.0)

        samples = [s for body in emitted for s in body.get("samples", [])]
        latencies = [m["value"] for m in samples if m["metric_name"] == "latency"]
        error_rates = [m["value"] for m in samples if m["metric_name"] == "error_rate"]
        request_rates = [m["value"] for m in samples if m["metric_name"] == "request_rate"]
        request_counts = [m["value"] for m in samples if m["metric_name"] == "request_count"]

        # All 6 individual request latencies preserved
        assert latencies == [40.0, 45.0, 50.0, 55.0, 60.0, 70.0]
        # Window 1 emitted 40.0% error rate, count 5, and 2.5 rps; Window 2 flushed count 1 & 0.0% error rate on stop
        assert error_rates[0] == 40.0
        assert error_rates[1] == 0.0
        assert request_counts == [5.0, 1.0]
        assert request_rates[0] == 2.5
        assert len(request_rates) == 2


@pytest.mark.asyncio
async def test_telemetry_short_window_and_health_exclusion():
    """Verify sub-100ms shutdown micro-windows omit extrapolated RPS and /health is never counted."""
    import json
    from fastapi.testclient import TestClient
    from services.order_service import main as order_main

    emitted = []

    async def capture_handler(request: httpx.Request) -> httpx.Response:
        emitted.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"accepted_count": 0, "anomalies_detected_count": 0, "results": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(capture_handler),
        base_url="http://mock-tm/api/v1",
    ) as mock_client:
        telemetry = TelemetryClient(
            service_identifier="order-service",
            base_url="http://mock-tm/api/v1",
            project_id=str(uuid4()),
            aggregation_interval_seconds=60.0,
        )
        telemetry._http_client = mock_client
        await telemetry.start()

        # Simulate 1 request flushed after only 0.01s (< 0.1s minimum rate window)
        t0 = 1000.0
        telemetry._window_start_monotonic = t0
        telemetry.record_request(latency_ms=25.0, is_error=False)
        res_short = telemetry.flush_window(now_monotonic=t0 + 0.01, allow_while_stopping=True)
        assert res_short == (0.0, None)
        await telemetry.stop(timeout=2.0)

        samples = [s for body in emitted for s in body.get("samples", [])]
        assert not any(m["metric_name"] == "request_rate" for m in samples)
        assert any(m["metric_name"] == "request_count" and m["value"] == 1.0 for m in samples)

    # Verify /health and /faults are excluded by ObservabilityMiddleware
    before_total = order_main.telemetry._window_total
    with TestClient(order_main.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/faults").status_code == 200
        assert order_main.telemetry._window_total == before_total



