"""Tests for Inventory Service."""

import pytest
import httpx
from common.models import (
    FaultConfig,
    FaultInjectionType,
    InventoryReserveRequest,
    OrderItem,
)
from services.inventory_service.main import app
from services.inventory_service.store import inventory_store


@pytest.fixture(autouse=True)
def reset_inventory_state():
    """Reset catalog stock and faults before each test."""
    inventory_store.reset()
    from services.inventory_service import main
    main.current_fault = FaultConfig()


@pytest.mark.asyncio
async def test_inventory_health():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "inventory-service"


@pytest.mark.asyncio
async def test_get_stock_for_known_and_unknown_sku():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Known SKU
        resp = await client.get("/inventory/SKU-LAPTOP-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sku"] == "SKU-LAPTOP-01"
        assert data["available_stock"] == 100

        # Unknown SKU
        resp_404 = await client.get("/inventory/SKU-NONEXISTENT")
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_reserve_inventory_success_and_stock_decrement():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        req = InventoryReserveRequest(
            order_id="ord-test-1",
            items=[OrderItem(sku="SKU-LAPTOP-01", quantity=2, unit_price=1299.99)],
        )
        resp = await client.post("/inventory/reserve", json=req.model_dump(mode="json"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RESERVED"
        assert len(data["reserved_items"]) == 1

        # Check stock decremented: 100 - 2 = 98
        stock_resp = await client.get("/inventory/SKU-LAPTOP-01")
        assert stock_resp.json()["available_stock"] == 98


@pytest.mark.asyncio
async def test_reserve_inventory_insufficient_stock():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        req = InventoryReserveRequest(
            order_id="ord-test-2",
            items=[OrderItem(sku="SKU-LAPTOP-01", quantity=500, unit_price=1299.99)],
        )
        resp = await client.post("/inventory/reserve", json=req.model_dump(mode="json"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "OUT_OF_STOCK"
        assert "Insufficient stock" in data["error_message"]


@pytest.mark.asyncio
async def test_inventory_fault_injection_and_reset():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Inject outage fault
        fault = FaultConfig(
            fault_type=FaultInjectionType.UNAVAILABLE,
            error_status_code=503,
            error_message="Warehouse database partition unmounted",
        )
        resp = await client.post("/faults", json=fault.model_dump(mode="json"))
        assert resp.status_code == 200

        # Query should now fail with 503
        resp_fail = await client.get("/inventory/SKU-LAPTOP-01")
        assert resp_fail.status_code == 503
        assert "Warehouse database partition" in resp_fail.json()["detail"]

        # Reset faults
        resp_reset = await client.post("/faults/reset")
        assert resp_reset.status_code == 200

        # Query should recover
        resp_ok = await client.get("/inventory/SKU-LAPTOP-01")
        assert resp_ok.status_code == 200

