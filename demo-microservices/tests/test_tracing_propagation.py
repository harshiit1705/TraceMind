"""Distributed trace propagation and parent-child span hierarchy tests across demo microservices."""

import asyncio
import json
from uuid import uuid4
import pytest
import httpx

from common.models import FaultConfig
from common.tracing import REQUEST_ID_HEADER, SPAN_ID_HEADER, TRACE_ID_HEADER
from services.order_service import main as order_main
from services.payment_service import main as pay_main
from services.inventory_service import main as inv_main
from services.inventory_service.store import inventory_store


@pytest.mark.asyncio
async def test_trace_propagation_parent_child_hierarchy_and_concurrent_isolation():
    """Verify trace IDs propagate Order -> Inventory & Payment with exact parent_span_id links
    and zero cross-talk under concurrent order requests."""
    captured_spans = []

    async def capture_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/telemetry/spans"):
            body = json.loads(request.content.decode("utf-8"))
            captured_spans.extend(body.get("spans", []))
            return httpx.Response(200, json={"accepted_count": len(body.get("spans", [])), "span_ids": []})
        if request.url.path.endswith("/telemetry/logs"):
            return httpx.Response(200, json={"accepted_count": 0, "log_ids": []})
        if request.url.path.endswith("/telemetry/metrics"):
            return httpx.Response(200, json={"accepted_count": 0, "anomalies_detected_count": 0, "results": []})
        return httpx.Response(200, json={})

    inventory_store.reset()
    inv_main.current_fault = FaultConfig()
    pay_main.current_fault = FaultConfig()
    order_main.current_fault = FaultConfig()
    order_main.orders_db.clear()

    project_id = str(uuid4())
    mock_tm = httpx.AsyncClient(
        transport=httpx.MockTransport(capture_handler),
        base_url="http://mock-tm/api/v1",
    )
    inv_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=inv_main.app), base_url="http://inventory-test")
    pay_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=pay_main.app), base_url="http://payment-test")
    order_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=order_main.app), base_url="http://order-test")

    order_main.clients._inventory_client = inv_client
    order_main.clients._payment_client = pay_client

    for svc_mod in (order_main, pay_main, inv_main):
        svc_mod.telemetry.enabled = True
        svc_mod.telemetry._resolved_project_id = None
        svc_mod.telemetry._configured_project_id = project_id
        from uuid import UUID
        svc_mod.telemetry._resolved_project_id = UUID(project_id)
        svc_mod.telemetry._http_client = mock_tm
        svc_mod.telemetry._owns_http_client = False
        await svc_mod.telemetry.start()

    try:
        payload_a = {
            "customer_id": "cust-trace-a",
            "items": [{"sku": "SKU-LAPTOP-01", "quantity": 1, "unit_price": 1299.99}],
            "payment_method": "card",
        }
        payload_b = {
            "customer_id": "cust-trace-b",
            "items": [{"sku": "SKU-KEYBOARD-04", "quantity": 1, "unit_price": 119.99}],
            "payment_method": "card",
        }

        resp_a, resp_b = await asyncio.gather(
            order_client.post("/orders", json=payload_a),
            order_client.post("/orders", json=payload_b),
        )
        assert resp_a.status_code == 201
        assert resp_b.status_code == 201

        trace_a = resp_a.headers.get(TRACE_ID_HEADER)
        trace_b = resp_b.headers.get(TRACE_ID_HEADER)
        req_a = resp_a.headers.get(REQUEST_ID_HEADER)
        req_b = resp_b.headers.get(REQUEST_ID_HEADER)
        assert trace_a and trace_b and trace_a != trace_b
        assert req_a and req_b and req_a != req_b
    finally:
        for svc_mod in (order_main, pay_main, inv_main):
            await svc_mod.telemetry.stop(timeout=3.0)
        await order_client.aclose()
        await pay_client.aclose()
        await inv_client.aclose()
        await mock_tm.aclose()

    spans_a = [s for s in captured_spans if s["trace_id"] == trace_a]
    spans_b = [s for s in captured_spans if s["trace_id"] == trace_b]
    assert len(spans_a) >= 7, f"Expected Order/Client/Inventory/Payment spans for trace A, got {len(spans_a)}"
    assert len(spans_b) >= 7

    # Root Order server span has parent_span_id=None
    roots_a = [s for s in spans_a if s["parent_span_id"] is None]
    assert len(roots_a) == 1
    order_root_a = roots_a[0]
    assert order_root_a["service_identifier"] == "order-service"
    assert order_root_a["span_kind"] == "server"
    assert order_root_a["operation_name"] == "POST /orders"

    # Client spans have parent_span_id == order root span_id
    by_span_id_a = {s["span_id"]: s for s in spans_a}
    inv_client_span = next(
        s for s in spans_a
        if s["service_identifier"] == "order-service" and s["span_kind"] == "client" and "inventory" in s["operation_name"].lower()
    )
    pay_client_span = next(
        s for s in spans_a
        if s["service_identifier"] == "order-service" and s["span_kind"] == "client" and "payment" in s["operation_name"].lower()
    )
    assert inv_client_span["parent_span_id"] == order_root_a["span_id"]
    assert pay_client_span["parent_span_id"] == order_root_a["span_id"]

    # Downstream server spans have parent_span_id matching respective Order client span
    inv_server_span = next(
        s for s in spans_a if s["service_identifier"] == "inventory-service" and s["span_kind"] == "server"
    )
    pay_server_span = next(
        s for s in spans_a if s["service_identifier"] == "payment-service" and s["span_kind"] == "server"
    )
    assert inv_server_span["parent_span_id"] == inv_client_span["span_id"]
    assert pay_server_span["parent_span_id"] == pay_client_span["span_id"]

    # Internal child spans sit beneath downstream server spans
    inv_internal = next(
        s for s in spans_a if s["service_identifier"] == "inventory-service" and s["span_kind"] == "internal"
    )
    pay_internal = next(
        s for s in spans_a if s["service_identifier"] == "payment-service" and s["span_kind"] == "internal"
    )
    assert inv_internal["parent_span_id"] == inv_server_span["span_id"]
    assert pay_internal["parent_span_id"] == pay_server_span["span_id"]
    assert pay_internal["attributes"].get("simulated_gateway") is True
    assert all(s["parent_span_id"] is None or s["parent_span_id"] in by_span_id_a for s in spans_a)

    # Confirm zero leakage between trace A and trace B
    span_ids_a = {s["span_id"] for s in spans_a}
    span_ids_b = {s["span_id"] for s in spans_b}
    assert span_ids_a.isdisjoint(span_ids_b)
