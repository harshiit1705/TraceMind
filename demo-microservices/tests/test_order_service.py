"""End-to-end tests for Order Service orchestrating Inventory and Payment Services."""

import pytest
import httpx
from common.models import FaultConfig, FaultInjectionType, OrderCreateRequest, OrderItem
from services.order_service import main as order_main
from services.inventory_service import main as inv_main
from services.payment_service import main as pay_main
from services.inventory_service.store import inventory_store


@pytest.fixture
def wired_order_clients(monkeypatch):
    """Wire Order Service downstream HTTP clients directly to in-memory ASGI apps for Inventory & Payment."""
    inv_store_orig = inventory_store.reset()
    inv_main.current_fault = FaultConfig()
    pay_main.current_fault = FaultConfig()
    order_main.current_fault = FaultConfig()
    order_main.orders_db.clear()

    inv_transport = httpx.ASGITransport(app=inv_main.app)
    pay_transport = httpx.ASGITransport(app=pay_main.app)

    inv_client = httpx.AsyncClient(transport=inv_transport, base_url="http://inventory-test")
    pay_client = httpx.AsyncClient(transport=pay_transport, base_url="http://payment-test")

    order_main.clients._inventory_client = inv_client
    order_main.clients._payment_client = pay_client

    return order_main.app, inv_client, pay_client


@pytest.mark.asyncio
async def test_order_checkout_happy_path(wired_order_clients):
    """Verify full checkout workflow across Order -> Inventory -> Payment."""
    app, inv_client, pay_client = wired_order_clients
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-e2e-1",
                items=[
                    OrderItem(sku="SKU-LAPTOP-01", quantity=1, unit_price=1299.99),
                    OrderItem(sku="SKU-MOUSE-05", quantity=2, unit_price=59.99),
                ],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 201
            data = resp.json()
            assert data["status"] == "CONFIRMED"
            assert data["total_amount"] == 1419.97
            assert data["payment_id"].startswith("pay-")

            # Verify order persisted in Order Service store
            order_id = data["order_id"]
            get_resp = await client.get(f"/orders/{order_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["status"] == "CONFIRMED"

            # Verify inventory decremented
            stock_resp = await inv_client.get("/inventory/SKU-LAPTOP-01")
            assert stock_resp.json()["available_stock"] == 99
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


@pytest.mark.asyncio
async def test_order_cascading_failure_from_inventory_outage(wired_order_clients):
    """Verify Order Service fails with 502 Bad Gateway when Inventory Service errors out."""
    app, inv_client, pay_client = wired_order_clients
    transport = httpx.ASGITransport(app=app)

    try:
        # Inject 503 outage in Inventory Service
        inv_main.current_fault = FaultConfig(
            fault_type=FaultInjectionType.UNAVAILABLE,
            error_status_code=503,
            error_message="Warehouse database lock contention",
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-fail-inv",
                items=[OrderItem(sku="SKU-PHONE-02", quantity=1, unit_price=799.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 502
            assert "inventory-service HTTP 503" in resp.json()["detail"]
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


@pytest.mark.asyncio
async def test_order_cascading_failure_from_payment_gateway_error(wired_order_clients):
    """Verify Order Service fails with 502 Bad Gateway when Payment Service fails."""
    app, inv_client, pay_client = wired_order_clients
    transport = httpx.ASGITransport(app=app)

    try:
        # Inject 100% 502 error in Payment Service
        pay_main.current_fault = FaultConfig(
            fault_type=FaultInjectionType.ERROR_RATE,
            error_rate_pct=100.0,
            error_status_code=502,
            error_message="Downstream processor timeout",
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-fail-pay",
                items=[OrderItem(sku="SKU-HEADPHONES-03", quantity=1, unit_price=199.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 502
            assert "payment-service HTTP 502" in resp.json()["detail"]
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


@pytest.mark.asyncio
async def test_order_telemetry_recorded_during_checkout(wired_order_clients, monkeypatch):
    """Verify telemetry metrics (individual latency + windowed error_rate & request_rate) are recorded on all three services."""
    app, inv_client, pay_client = wired_order_clients
    transport = httpx.ASGITransport(app=app)

    recorded_metrics = []

    def spy_record(svc_name):
        def _recorder(metric_name, observed_value, **kwargs):
            recorded_metrics.append((svc_name, metric_name, observed_value))
            return True
        return _recorder

    for svc_mod, svc_name in [
        (order_main, "order-service"),
        (inv_main, "inventory-service"),
        (pay_main, "payment-service"),
    ]:
        svc_mod.telemetry.enabled = True
        svc_mod.telemetry._shutting_down = False
        svc_mod.telemetry._window_total = 0
        svc_mod.telemetry._window_errors = 0
        monkeypatch.setattr(svc_mod.telemetry, "record_measurement", spy_record(svc_name))

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-telemetry",
                items=[OrderItem(sku="SKU-KEYBOARD-04", quantity=1, unit_price=119.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 201

        # Immediately after checkout, individual latency was recorded
        assert all(
            any(m[0] == s and m[1] == "latency" and m[2] > 0.0 for m in recorded_metrics)
            for s in ("order-service", "inventory-service", "payment-service")
        )

        # Flush aggregation windows on all 3 services
        order_main.telemetry.flush_window()
        inv_main.telemetry.flush_window()
        pay_main.telemetry.flush_window()

        services_reported = {m[0] for m in recorded_metrics}
        assert services_reported == {"order-service", "inventory-service", "payment-service"}

        for svc in services_reported:
            svc_metrics = {m[1]: m[2] for m in recorded_metrics if m[0] == svc}
            assert "latency" in svc_metrics
            assert svc_metrics["latency"] > 0.0
            assert svc_metrics["error_rate"] == 0.0
            assert svc_metrics["request_rate"] > 0.0
    finally:
        await inv_client.aclose()
        await pay_client.aclose()

