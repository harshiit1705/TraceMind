"""Tests for TrafficGenerator, ScenarioRunner, and CLI."""

import pytest
import httpx

from common.models import FaultConfig
from services.order_service import main as order_main
from services.payment_service import main as pay_main
from services.inventory_service import main as inv_main
from services.inventory_service.store import inventory_store
from simulator.scenarios import ScenarioRunner
from simulator.cli import build_parser, execute_cli


@pytest.fixture
def wired_scenario_runner():
    """Wire ScenarioRunner directly to in-memory ASGI apps for Order, Payment, Inventory, and TraceMind."""
    inventory_store.reset()
    inv_main.current_fault = FaultConfig()
    pay_main.current_fault = FaultConfig()
    order_main.current_fault = FaultConfig()
    order_main.orders_db.clear()

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

    # Wire Order Service downstream clients
    order_main.clients._inventory_client = inv_client
    order_main.clients._payment_client = pay_client

    # Disable real network telemetry dispatch during unit tests
    order_main.telemetry.enabled = False
    pay_main.telemetry.enabled = False
    inv_main.telemetry.enabled = False

    runner = ScenarioRunner(
        order_client=order_client,
        payment_client=pay_client,
        inventory_client=inv_client,
    )
    return runner, order_client, pay_client, inv_client


@pytest.mark.asyncio
async def test_traffic_generator_normal_batch(wired_scenario_runner):
    runner, order_client, pay_client, inv_client = wired_scenario_runner
    try:
        summary = await runner.run_normal_traffic(count=4, interval_sec=0.01)
        assert summary.total_requests == 4
        assert summary.confirmed_count == 4
        assert summary.failed_count == 0
        assert summary.avg_latency_ms > 0.0
    finally:
        await order_client.aclose()
        await pay_client.aclose()
        await inv_client.aclose()


@pytest.mark.asyncio
async def test_inventory_latency_scenario_and_controlled_correlation(wired_scenario_runner, monkeypatch):
    runner, order_client, pay_client, inv_client = wired_scenario_runner
    correlation_calls = []

    async def mock_correlate(window_seconds: int = 300):
        correlation_calls.append(window_seconds)
        return {"correlation_groups_count": 1, "total_anomalies_evaluated": 2}

    monkeypatch.setattr(runner, "trigger_correlation_evaluation", mock_correlate)

    try:
        result = await runner.run_inventory_latency_spike(
            delay_ms=120.0,
            requests=3,
            settle_delay_sec=0.01,
            trigger_correlation=True,
        )
        assert result["scenario"] == "inventory-latency"
        assert result["traffic_summary"]["total_requests"] == 3
        assert result["traffic_summary"]["confirmed"] == 3
        assert result["traffic_summary"]["avg_latency_ms"] >= 120.0
        # Verify correlation was triggered exactly ONCE after the batch, NOT per request
        assert len(correlation_calls) == 1
        assert result["correlation_result"]["correlation_groups_count"] == 1
    finally:
        await order_client.aclose()
        await pay_client.aclose()
        await inv_client.aclose()


@pytest.mark.asyncio
async def test_payment_error_spike_and_recovery_scenarios(wired_scenario_runner, monkeypatch):
    runner, order_client, pay_client, inv_client = wired_scenario_runner
    correlation_calls = []

    async def mock_correlate(window_seconds: int = 300):
        correlation_calls.append(window_seconds)
        return {"correlation_groups_count": 1, "total_anomalies_evaluated": 2}

    monkeypatch.setattr(runner, "trigger_correlation_evaluation", mock_correlate)

    try:
        # 1. Payment Error Spike
        err_result = await runner.run_payment_error_spike(
            error_pct=100.0,
            status_code=502,
            requests=3,
            settle_delay_sec=0.01,
            trigger_correlation=True,
        )
        assert err_result["scenario"] == "payment-errors"
        assert err_result["traffic_summary"]["total_requests"] == 3
        assert err_result["traffic_summary"]["failed"] == 3
        assert err_result["traffic_summary"]["confirmed"] == 0
        assert len(correlation_calls) == 1

        # 2. Recovery
        rec_result = await runner.run_recovery(count=3, interval_sec=0.01)
        assert rec_result["scenario"] == "recover"
        assert rec_result["traffic_summary"]["confirmed"] == 3
        assert rec_result["traffic_summary"]["failed"] == 0
    finally:
        await order_client.aclose()
        await pay_client.aclose()
        await inv_client.aclose()


@pytest.mark.asyncio
async def test_cli_command_execution(wired_scenario_runner):
    runner, order_client, pay_client, inv_client = wired_scenario_runner
    parser = build_parser()

    try:
        # status
        args_status = parser.parse_args(["status"])
        res_status = await execute_cli(args_status, runner=runner)
        assert "order-service" in res_status
        assert res_status["order-service"]["health"]["status"] == "healthy"

        # traffic
        args_traffic = parser.parse_args(["traffic", "--count", "2", "--interval", "0.01"])
        res_traffic = await execute_cli(args_traffic, runner=runner)
        assert res_traffic["total_requests"] == 2
        assert res_traffic["confirmed"] == 2

        # faults-reset
        args_reset = parser.parse_args(["faults-reset"])
        res_reset = await execute_cli(args_reset, runner=runner)
        assert res_reset["inventory-service"]["fault_type"] == "none"
    finally:
        await order_client.aclose()
        await pay_client.aclose()
        await inv_client.aclose()

