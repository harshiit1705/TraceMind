"""Structured logging tests for demo microservices middleware and downstream failure diagnostics."""

import json
from uuid import UUID, uuid4
import pytest
import httpx

from common.models import FaultConfig, FaultInjectionType
from common.tracing import TRACE_ID_HEADER
from services.order_service import main as order_main
from services.payment_service import main as pay_main
from services.inventory_service import main as inv_main
from services.inventory_service.store import inventory_store


@pytest.mark.asyncio
async def test_structured_logs_carry_trace_context_and_capture_payment_error():
    """Verify INFO logs on normal requests, ERROR logs on upstream HTTP 502, and trace correlation."""
    captured_logs = []

    async def capture_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/telemetry/logs"):
            body = json.loads(request.content.decode("utf-8"))
            captured_logs.extend(body.get("logs", []))
            return httpx.Response(200, json={"accepted_count": len(body.get("logs", [])), "log_ids": []})
        if request.url.path.endswith("/telemetry/spans"):
            return httpx.Response(200, json={"accepted_count": 0, "span_ids": []})
        if request.url.path.endswith("/telemetry/metrics"):
            return httpx.Response(200, json={"accepted_count": 0, "anomalies_detected_count": 0, "results": []})
        return httpx.Response(200, json={})

    inventory_store.reset()
    inv_main.current_fault = FaultConfig()
    pay_main.current_fault = FaultConfig(
        fault_type=FaultInjectionType.ERROR_RATE,
        error_rate_pct=100.0,
        error_status_code=502,
        error_message="Simulated payment settlement outage",
    )
    order_main.current_fault = FaultConfig()
    order_main.orders_db.clear()

    project_id = str(uuid4())
    mock_tm = httpx.AsyncClient(transport=httpx.MockTransport(capture_handler), base_url="http://mock-tm/api/v1")
    inv_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=inv_main.app), base_url="http://inventory-test")
    pay_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=pay_main.app), base_url="http://payment-test")
    order_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=order_main.app), base_url="http://order-test")

    order_main.clients._inventory_client = inv_client
    order_main.clients._payment_client = pay_client

    for svc_mod in (order_main, pay_main, inv_main):
        svc_mod.telemetry.enabled = True
        svc_mod.telemetry._configured_project_id = project_id
        svc_mod.telemetry._resolved_project_id = UUID(project_id)
        svc_mod.telemetry._http_client = mock_tm
        svc_mod.telemetry._owns_http_client = False
        await svc_mod.telemetry.start()

    try:
        resp = await order_client.post(
            "/orders",
            json={
                "customer_id": "cust-log-err",
                "items": [{"sku": "SKU-LAPTOP-01", "quantity": 1, "unit_price": 1299.99}],
                "payment_method": "card",
            },
            headers={"Authorization": "Bearer super-secret-jwt-token"},
        )
        assert resp.status_code == 502
        trace_id = resp.headers.get(TRACE_ID_HEADER)
        assert trace_id
    finally:
        pay_main.current_fault = FaultConfig()
        for svc_mod in (order_main, pay_main, inv_main):
            await svc_mod.telemetry.stop(timeout=3.0)
        await order_client.aclose()
        await pay_client.aclose()
        await inv_client.aclose()
        await mock_tm.aclose()

    trace_logs = [entry for entry in captured_logs if entry.get("trace_id") == trace_id]
    assert len(trace_logs) >= 3

    by_service = {}
    for entry in trace_logs:
        by_service.setdefault(entry["service_identifier"], []).append(entry)

    assert "inventory-service" in by_service
    assert "payment-service" in by_service
    assert "order-service" in by_service

    # Inventory succeeded -> INFO
    assert any(log["level"] == "INFO" for log in by_service["inventory-service"])
    # Payment returned 502 -> ERROR with exception_message
    pay_errors = [log for log in by_service["payment-service"] if log["level"] == "ERROR"]
    assert len(pay_errors) >= 1
    assert pay_errors[0]["span_id"] is not None
    assert pay_errors[0]["request_id"] is not None
    # Order cascaded 502 -> ERROR
    assert any(log["level"] == "ERROR" for log in by_service["order-service"])
    # Secret header never leaked into log message or attributes
    serialized = json.dumps(trace_logs)
    assert "super-secret-jwt-token" not in serialized
