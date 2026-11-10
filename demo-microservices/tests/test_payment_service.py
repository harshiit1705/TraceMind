"""Tests for Payment Service."""

import time
import pytest
import httpx
from common.models import FaultConfig, FaultInjectionType, PaymentRequest
from services.payment_service.main import app


@pytest.fixture(autouse=True)
def reset_payment_state():
    """Reset faults before each test."""
    from services.payment_service import main
    main.current_fault = FaultConfig()


@pytest.mark.asyncio
async def test_payment_health():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "payment-service"


@pytest.mark.asyncio
async def test_payment_charge_success():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        req = PaymentRequest(
            order_id="ord-pay-1",
            customer_id="cust-1001",
            amount=149.99,
        )
        resp = await client.post("/payments/charge", json=req.model_dump(mode="json"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["payment_id"].startswith("pay-")
        assert data["amount"] == 149.99


@pytest.mark.asyncio
async def test_payment_fault_injection_latency_and_errors():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Inject 100% error rate fault
        fault_err = FaultConfig(
            fault_type=FaultInjectionType.ERROR_RATE,
            error_rate_pct=100.0,
            error_status_code=502,
            error_message="Stripe gateway 502 error",
        )
        await client.post("/faults", json=fault_err.model_dump(mode="json"))

        req = PaymentRequest(order_id="ord-pay-fail", customer_id="cust-1001", amount=50.0)
        resp = await client.post("/payments/charge", json=req.model_dump(mode="json"))
        assert resp.status_code == 502
        assert "Stripe gateway 502 error" in resp.json()["detail"]

        # 2. Inject latency fault (150ms)
        fault_lat = FaultConfig(
            fault_type=FaultInjectionType.LATENCY,
            latency_delay_ms=150.0,
        )
        await client.post("/faults", json=fault_lat.model_dump(mode="json"))

        t0 = time.perf_counter()
        resp_slow = await client.post("/payments/charge", json=req.model_dump(mode="json"))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert resp_slow.status_code == 200
        assert elapsed_ms >= 150.0

        # 3. Reset
        await client.post("/faults/reset")
        resp_ok = await client.post("/payments/charge", json=req.model_dump(mode="json"))
        assert resp_ok.status_code == 200

