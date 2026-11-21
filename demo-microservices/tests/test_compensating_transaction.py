"""Tests for Compensating Transactions across Order Service and Inventory Service.

Verifies:
1. Normal inventory reservation and release.
2. Duplicate release idempotency (stock not inflated).
3. Invalid or unknown reservation returns meaningful HTTP 404/400.
4. Payment rejection after reservation triggers compensation (stock restored, original 402 preserved).
5. Payment-service HTTP 502 failure triggers compensation (stock restored, original 502 preserved).
6. Payment-service timeout triggers compensation (stock restored, original 504 preserved).
7. Inventory reservation failure does not trigger release.
8. Successful checkout does not trigger release (stock remains decremented).
9. Compensation failure is explicitly recorded and does not overwrite the original payment error.
10. Concurrent release requests preserve stock consistency without inflation.
"""

import asyncio
import pytest
import httpx

from common.models import (
    FaultConfig,
    FaultInjectionType,
    InventoryReleaseRequest,
    InventoryReserveRequest,
    OrderCreateRequest,
    OrderItem,
    OrderStatus,
    PaymentResponse,
    PaymentStatus,
)
from services.inventory_service import main as inv_main
from services.inventory_service.store import inventory_store
from services.order_service import main as order_main
from services.payment_service import main as pay_main


@pytest.fixture(autouse=True)
def reset_service_states():
    """Reset catalog, fault configs, and order storage before each test."""
    inventory_store.reset()
    inv_main.current_fault = FaultConfig()
    pay_main.current_fault = FaultConfig()
    order_main.current_fault = FaultConfig()
    order_main.orders_db.clear()
    yield
    inventory_store.reset()
    inv_main.current_fault = FaultConfig()
    pay_main.current_fault = FaultConfig()
    order_main.current_fault = FaultConfig()
    order_main.orders_db.clear()


@pytest.fixture
def wired_clients():
    """Wire Order Service downstream clients directly to ASGI apps."""
    inv_transport = httpx.ASGITransport(app=inv_main.app)
    pay_transport = httpx.ASGITransport(app=pay_main.app)

    inv_client = httpx.AsyncClient(transport=inv_transport, base_url="http://inventory-test")
    pay_client = httpx.AsyncClient(transport=pay_transport, base_url="http://payment-test")

    order_main.clients._inventory_client = inv_client
    order_main.clients._payment_client = pay_client

    return order_main.app, inv_client, pay_client


# ---------------------------------------------------------------------------
# 1. Normal inventory reservation and release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inventory_reserve_and_release_normal():
    """Normal inventory reservation decrements stock; release restores exact stock."""
    transport = httpx.ASGITransport(app=inv_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://inventory-test") as client:
        # Step 1: Initial stock = 100
        item_before = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_before.json()["available_stock"] == 100

        # Step 2: Reserve 2 units for order-001
        res_req = InventoryReserveRequest(
            order_id="ord-comp-001",
            items=[OrderItem(sku="SKU-LAPTOP-01", quantity=2, unit_price=1299.99)],
        )
        res_resp = await client.post("/inventory/reserve", json=res_req.model_dump(mode="json"))
        assert res_resp.status_code == 200
        assert res_resp.json()["status"] == "RESERVED"

        item_mid = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_mid.json()["available_stock"] == 98

        # Step 3: Release reservation
        rel_req = InventoryReleaseRequest(order_id="ord-comp-001", reason="payment_failed")
        rel_resp = await client.post("/inventory/release", json=rel_req.model_dump(mode="json"))
        assert rel_resp.status_code == 200
        data = rel_resp.json()
        assert data["status"] == "RELEASED"
        assert len(data["released_items"]) == 1
        assert data["released_items"][0]["sku"] == "SKU-LAPTOP-01"
        assert data["released_items"][0]["quantity"] == 2

        # Step 4: Verify stock restored to exactly 100
        item_after = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_after.json()["available_stock"] == 100


# ---------------------------------------------------------------------------
# 2. Duplicate release idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inventory_duplicate_release_idempotency_prevents_stock_inflation():
    """Calling release multiple times is idempotent and never inflates stock beyond initial levels."""
    transport = httpx.ASGITransport(app=inv_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://inventory-test") as client:
        # Reserve 5 units (100 -> 95)
        res_req = InventoryReserveRequest(
            order_id="ord-comp-idem",
            items=[OrderItem(sku="SKU-LAPTOP-01", quantity=5, unit_price=1299.99)],
        )
        await client.post("/inventory/reserve", json=res_req.model_dump(mode="json"))

        item_res = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_res.json()["available_stock"] == 95

        # First release (95 -> 100)
        rel_req = InventoryReleaseRequest(order_id="ord-comp-idem")
        rel1 = await client.post("/inventory/release", json=rel_req.model_dump(mode="json"))
        assert rel1.status_code == 200
        assert rel1.json()["status"] == "RELEASED"

        item_rel1 = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_rel1.json()["available_stock"] == 100

        # Second release (must NOT increase stock to 105!)
        rel2 = await client.post("/inventory/release", json=rel_req.model_dump(mode="json"))
        assert rel2.status_code == 200
        assert rel2.json()["status"] == "RELEASED"

        item_rel2 = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_rel2.json()["available_stock"] == 100

        # Third release
        rel3 = await client.post("/inventory/release", json=rel_req.model_dump(mode="json"))
        assert rel3.status_code == 200
        assert rel3.json()["status"] == "RELEASED"

        item_rel3 = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_rel3.json()["available_stock"] == 100


# ---------------------------------------------------------------------------
# 3. Invalid or unknown reservation returns HTTP 404/400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inventory_release_unknown_or_invalid_reservation():
    """Releasing an unknown reservation returns 404; invalid payload returns 400 or 422."""
    transport = httpx.ASGITransport(app=inv_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://inventory-test") as client:
        # Unknown order_id -> 404
        rel_req = InventoryReleaseRequest(order_id="ord-nonexistent-999")
        resp = await client.post("/inventory/release", json=rel_req.model_dump(mode="json"))
        assert resp.status_code == 404
        assert "No reservation found" in resp.json()["detail"]

        # Stock remains untouched
        stock = await client.get("/inventory/SKU-LAPTOP-01")
        assert stock.json()["available_stock"] == 100


# ---------------------------------------------------------------------------
# 4. Payment rejection after reservation triggers compensation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_rejection_triggers_inventory_compensation(wired_clients, monkeypatch):
    """When payment responds with FAILED status, order fails with 402 and inventory is compensated."""
    app, inv_client, pay_client = wired_clients
    transport = httpx.ASGITransport(app=app)

    # Mock payment client to return a rejected PaymentResponse
    async def mock_charge_rejected(*args, **kwargs):
        return PaymentResponse(
            payment_id="pay-rejected-001",
            order_id="test",
            amount=1299.99,
            status=PaymentStatus.FAILED,
            error_message="Insufficient customer credit limit",
        )

    monkeypatch.setattr(order_main.clients, "charge_payment", mock_charge_rejected)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-comp-reject",
                items=[OrderItem(sku="SKU-LAPTOP-01", quantity=3, unit_price=1299.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 402
            assert "Insufficient customer credit limit" in resp.json()["detail"]

            # Verify inventory was restored to 100 (not left at 97)
            stock_resp = await inv_client.get("/inventory/SKU-LAPTOP-01")
            assert stock_resp.json()["available_stock"] == 100

            # Verify order record in Order Service DB explicitly records compensation
            orders = list(order_main.orders_db.values())
            assert len(orders) == 1
            order = orders[0]
            assert order.status == OrderStatus.FAILED
            assert order.compensation_status == "COMPENSATED"
            assert order.error_message == "Insufficient customer credit limit"
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


# ---------------------------------------------------------------------------
# 5. Payment-service HTTP 502 failure triggers compensation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_service_http_502_triggers_inventory_compensation(wired_clients):
    """When Payment Service returns HTTP 502, order returns 502 and inventory is compensated."""
    app, inv_client, pay_client = wired_clients
    transport = httpx.ASGITransport(app=app)

    try:
        # Inject 100% 502 error in Payment Service
        pay_main.current_fault = FaultConfig(
            fault_type=FaultInjectionType.ERROR_RATE,
            error_rate_pct=100.0,
            error_status_code=502,
            error_message="Downstream card processor timeout",
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-comp-502",
                items=[OrderItem(sku="SKU-PHONE-02", quantity=2, unit_price=799.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 502
            assert "payment-service HTTP 502" in resp.json()["detail"]

            # Verify inventory was restored to 150 (not left at 148)
            stock_resp = await inv_client.get("/inventory/SKU-PHONE-02")
            assert stock_resp.json()["available_stock"] == 150

            # Verify order record in Order Service DB records compensation
            orders = list(order_main.orders_db.values())
            assert len(orders) == 1
            order = orders[0]
            assert order.status == OrderStatus.FAILED
            assert order.compensation_status == "COMPENSATED"
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


# ---------------------------------------------------------------------------
# 6. Payment-service timeout triggers compensation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_service_timeout_triggers_inventory_compensation(wired_clients, monkeypatch):
    """When Payment Service call times out, order returns 504 and inventory is compensated."""
    app, inv_client, pay_client = wired_clients
    transport = httpx.ASGITransport(app=app)

    from services.order_service.client import DownstreamServiceError

    async def mock_charge_timeout(*args, **kwargs):
        raise DownstreamServiceError("payment-service", 504, "Payment settlement timed out")

    monkeypatch.setattr(order_main.clients, "charge_payment", mock_charge_timeout)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-comp-timeout",
                items=[OrderItem(sku="SKU-KEYBOARD-04", quantity=4, unit_price=119.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 504
            assert "Payment settlement timed out" in resp.json()["detail"]

            # Verify inventory was restored to 300 (not left at 296)
            stock_resp = await inv_client.get("/inventory/SKU-KEYBOARD-04")
            assert stock_resp.json()["available_stock"] == 300

            orders = list(order_main.orders_db.values())
            assert len(orders) == 1
            order = orders[0]
            assert order.status == OrderStatus.FAILED
            assert order.compensation_status == "COMPENSATED"
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


# ---------------------------------------------------------------------------
# 7. Inventory reservation failure does not trigger release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inventory_reservation_failure_does_not_trigger_release(wired_clients, monkeypatch):
    """When inventory reservation fails (e.g. out of stock), release is not attempted."""
    app, inv_client, pay_client = wired_clients
    transport = httpx.ASGITransport(app=app)

    release_called = False
    original_release = order_main.clients.release_inventory

    async def spy_release(*args, **kwargs):
        nonlocal release_called
        release_called = True
        return await original_release(*args, **kwargs)

    monkeypatch.setattr(order_main.clients, "release_inventory", spy_release)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            # Request 9999 units (stock is 100)
            req = OrderCreateRequest(
                customer_id="cust-comp-nostock",
                items=[OrderItem(sku="SKU-LAPTOP-01", quantity=9999, unit_price=1299.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 400
            assert "Inventory reservation failed" in resp.json()["detail"]

            # Release was never called
            assert release_called is False

            # Stock untouched at 100
            stock_resp = await inv_client.get("/inventory/SKU-LAPTOP-01")
            assert stock_resp.json()["available_stock"] == 100
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


# ---------------------------------------------------------------------------
# 8. Successful checkout does not trigger release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_checkout_does_not_trigger_release(wired_clients, monkeypatch):
    """Happy path checkout reserves inventory and completes without calling release."""
    app, inv_client, pay_client = wired_clients
    transport = httpx.ASGITransport(app=app)

    release_called = False
    original_release = order_main.clients.release_inventory

    async def spy_release(*args, **kwargs):
        nonlocal release_called
        release_called = True
        return await original_release(*args, **kwargs)

    monkeypatch.setattr(order_main.clients, "release_inventory", spy_release)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-comp-happy",
                items=[OrderItem(sku="SKU-MOUSE-05", quantity=3, unit_price=59.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))
            assert resp.status_code == 201
            assert resp.json()["status"] == "CONFIRMED"

            # Release must not have been called
            assert release_called is False

            # Stock stays decremented: 400 - 3 = 397
            stock_resp = await inv_client.get("/inventory/SKU-MOUSE-05")
            assert stock_resp.json()["available_stock"] == 397
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


# ---------------------------------------------------------------------------
# 9. Compensation failure explicitly recorded; preserves original error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compensation_failure_recorded_and_preserves_payment_error(wired_clients, monkeypatch):
    """If release fails during compensation, the primary error is still the payment error, and compensation failure is explicitly recorded."""
    app, inv_client, pay_client = wired_clients
    transport = httpx.ASGITransport(app=app)

    from services.order_service.client import DownstreamServiceError

    # Payment fails with 502
    async def mock_charge_fail(*args, **kwargs):
        raise DownstreamServiceError("payment-service", 502, "Payment network partition")

    # Release also fails (e.g. inventory cluster unreachable)
    async def mock_release_fail(*args, **kwargs):
        raise DownstreamServiceError("inventory-service", 503, "Inventory cluster dead")

    monkeypatch.setattr(order_main.clients, "charge_payment", mock_charge_fail)
    monkeypatch.setattr(order_main.clients, "release_inventory", mock_release_fail)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://order-test") as client:
            req = OrderCreateRequest(
                customer_id="cust-comp-double-fail",
                items=[OrderItem(sku="SKU-HEADPHONES-03", quantity=1, unit_price=199.99)],
            )
            resp = await client.post("/orders", json=req.model_dump(mode="json"))

            # Primary error remains the payment failure: 502 Bad Gateway
            assert resp.status_code == 502
            assert "payment-service HTTP 502" in resp.json()["detail"]
            assert "Payment network partition" in resp.json()["detail"]

            # Order record shows COMPENSATION_FAILED, not success
            orders = list(order_main.orders_db.values())
            assert len(orders) == 1
            order = orders[0]
            assert order.status == OrderStatus.FAILED
            assert order.compensation_status == "COMPENSATION_FAILED"
            assert "Inventory cluster dead" in order.compensation_error
            assert "Payment network partition" in order.error_message
    finally:
        await inv_client.aclose()
        await pay_client.aclose()


# ---------------------------------------------------------------------------
# 10. Concurrency safety: concurrent release requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_releases_preserve_stock_consistency():
    """Concurrent release calls on the same order do not inflate stock."""
    transport = httpx.ASGITransport(app=inv_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://inventory-test") as client:
        # Reserve 10 laptops (100 -> 90)
        res_req = InventoryReserveRequest(
            order_id="ord-comp-concurrent",
            items=[OrderItem(sku="SKU-LAPTOP-01", quantity=10, unit_price=1299.99)],
        )
        await client.post("/inventory/reserve", json=res_req.model_dump(mode="json"))

        item_mid = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_mid.json()["available_stock"] == 90

        # Launch 5 concurrent release requests for the same order
        rel_req = InventoryReleaseRequest(order_id="ord-comp-concurrent")

        async def _do_release():
            return await client.post("/inventory/release", json=rel_req.model_dump(mode="json"))

        responses = await asyncio.gather(*[_do_release() for _ in range(5)])

        # All 5 return 200
        for r in responses:
            assert r.status_code == 200
            assert r.json()["status"] == "RELEASED"

        # Final stock must be exactly 100 (never 110, 120, etc.)
        item_final = await client.get("/inventory/SKU-LAPTOP-01")
        assert item_final.json()["available_stock"] == 100
