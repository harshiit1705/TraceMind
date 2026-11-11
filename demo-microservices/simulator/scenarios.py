"""Controlled fault injection and scenario runner for demo microservices."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID
import httpx

from common.config import config
from common.models import FaultConfig, FaultInjectionType
from simulator.traffic_generator import TrafficGenerator, TrafficSummary

logger = logging.getLogger("demo_microservices.simulator.scenarios")


class ScenarioRunner:
    """Orchestrates repeatable baseline, fault injection, recovery, and correlation workflows."""

    def __init__(
        self,
        order_url: Optional[str] = None,
        payment_url: Optional[str] = None,
        inventory_url: Optional[str] = None,
        tracemind_url: Optional[str] = None,
        project_slug: Optional[str] = None,
        project_id: Optional[str] = None,
        order_client: Optional[httpx.AsyncClient] = None,
        payment_client: Optional[httpx.AsyncClient] = None,
        inventory_client: Optional[httpx.AsyncClient] = None,
        tracemind_client: Optional[httpx.AsyncClient] = None,
    ):
        self.order_url = (order_url or config.get_order_url()).rstrip("/")
        self.payment_url = (payment_url or config.get_payment_url()).rstrip("/")
        self.inventory_url = (inventory_url or config.get_inventory_url()).rstrip("/")
        self.tracemind_url = (tracemind_url or config.TRACEMIND_API_URL).rstrip("/")
        self.project_slug = project_slug if project_slug is not None else config.PROJECT_SLUG
        self._configured_project_id = project_id if project_id is not None else config.PROJECT_ID

        self._order_client = order_client
        self._payment_client = payment_client
        self._inventory_client = inventory_client
        self._tracemind_client = tracemind_client

        self.traffic = TrafficGenerator(
            order_url=self.order_url,
            http_client=self._order_client,
        )

    async def _post_service(
        self,
        service_client: Optional[httpx.AsyncClient],
        base_url: str,
        path: str,
        json_payload: Optional[dict] = None,
    ) -> dict:
        client = service_client or httpx.AsyncClient(base_url=base_url, timeout=5.0)
        own = client != service_client
        try:
            resp = await client.post(path, json=json_payload)
            resp.raise_for_status()
            return resp.json()
        finally:
            if own:
                await client.aclose()

    async def _get_service(
        self,
        service_client: Optional[httpx.AsyncClient],
        base_url: str,
        path: str,
    ) -> dict:
        client = service_client or httpx.AsyncClient(base_url=base_url, timeout=5.0)
        own = client != service_client
        try:
            resp = await client.get(path)
            resp.raise_for_status()
            return resp.json()
        finally:
            if own:
                await client.aclose()

    async def reset_all_faults(self) -> Dict[str, Any]:
        """Reset fault configurations on Order, Payment, and Inventory Services."""
        results = {}
        for name, client, url in [
            ("order-service", self._order_client, self.order_url),
            ("payment-service", self._payment_client, self.payment_url),
            ("inventory-service", self._inventory_client, self.inventory_url),
        ]:
            results[name] = await self._post_service(client, url, "/faults/reset")
        logger.info("All service faults reset to healthy defaults.")
        return results

    async def get_all_status(self) -> Dict[str, Any]:
        """Retrieve health and active fault configs from all three microservices."""
        status_report = {}
        for name, client, url in [
            ("order-service", self._order_client, self.order_url),
            ("payment-service", self._payment_client, self.payment_url),
            ("inventory-service", self._inventory_client, self.inventory_url),
        ]:
            try:
                health = await self._get_service(client, url, "/health")
                fault = await self._get_service(client, url, "/faults")
                status_report[name] = {"health": health, "fault": fault}
            except Exception as exc:
                status_report[name] = {"health": "unreachable", "error": str(exc)}
        return status_report

    async def resolve_project_id(self) -> Optional[str]:
        """Fetch target project ID strictly matching configured project_id or project_slug."""
        if self._configured_project_id:
            try:
                UUID(self._configured_project_id)
                return self._configured_project_id
            except ValueError:
                logger.error(
                    "Configured PROJECT_ID '%s' is not a valid UUID; failing closed.",
                    self._configured_project_id,
                )
                return None

        client = self._tracemind_client or httpx.AsyncClient(
            base_url=self.tracemind_url, timeout=5.0
        )
        own = client != self._tracemind_client
        try:
            resp = await client.get("/projects")
            if resp.status_code == 200:
                projects = resp.json()
                match = next((p for p in projects if p.get("slug") == self.project_slug), None)
                if match:
                    return match["id"]

                logger.error(
                    "TraceMind project with slug '%s' was not found (available: %s). "
                    "Failing closed; correlation evaluation skipped.",
                    self.project_slug,
                    [p.get("slug") for p in projects],
                )
                return None

            logger.warning(
                "TraceMind returned HTTP %d while resolving project slug '%s' from %s",
                resp.status_code,
                self.project_slug,
                self.tracemind_url,
            )
        except Exception as exc:
            logger.warning("Could not fetch project_id from TraceMind (%s): %s", self.tracemind_url, str(exc))
        finally:
            if own:
                await client.aclose()
        return None

    async def trigger_correlation_evaluation(
        self,
        window_seconds: int = 300,
    ) -> Optional[dict]:
        """Call TraceMind /correlations/evaluate for the recent window.

        Designed to run at controlled intervals after a scenario batch rather than
        per individual HTTP request.
        """
        project_id = await self.resolve_project_id()
        if not project_id:
            logger.warning("Skipping correlation evaluation: unable to resolve project_id.")
            return None

        now_utc = datetime.now(timezone.utc)
        start_utc = now_utc - timedelta(seconds=window_seconds)

        payload = {
            "project_id": project_id,
            "start_time": start_utc.isoformat(),
            "end_time": now_utc.isoformat(),
        }

        client = self._tracemind_client or httpx.AsyncClient(
            base_url=self.tracemind_url, timeout=10.0
        )
        own = client != self._tracemind_client
        try:
            resp = await client.post("/correlations/evaluate", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                logger.info(
                    "Correlation evaluation complete: %d groups formed from %d anomalies evaluated.",
                    data.get("correlation_groups_count", 0),
                    data.get("total_anomalies_evaluated", 0),
                )
                return data
            logger.warning("TraceMind correlation evaluation returned %d: %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.warning("TraceMind correlation evaluation failed: %s", str(exc))
        finally:
            if own:
                await client.aclose()
        return None

    async def run_normal_traffic(
        self,
        count: int = 10,
        interval_sec: float = 0.15,
    ) -> TrafficSummary:
        """Scenario 1: Reset faults and run steady-state traffic to warm up & establish baselines."""
        logger.info("Starting Scenario 1: Normal Steady-State Traffic (%d requests)...", count)
        await self.reset_all_faults()
        return await self.traffic.run_batch(count=count, interval_sec=interval_sec)

    async def run_inventory_latency_spike(
        self,
        delay_ms: float = 650.0,
        requests: int = 5,
        warmup_count: int = 0,
        settle_delay_sec: float = 0.5,
        trigger_correlation: bool = True,
        reset_prior: bool = True,
    ) -> Dict[str, Any]:
        """Scenario 2: Inject database lock latency spike in Inventory Service."""
        if reset_prior:
            await self.reset_all_faults()
        if warmup_count > 0:
            await self.run_normal_traffic(count=warmup_count, interval_sec=0.1)

        logger.info(
            "Starting Scenario 2: Inventory Latency Spike (+%.1fms delay for %d requests)...",
            delay_ms,
            requests,
        )
        fault = FaultConfig(
            fault_type=FaultInjectionType.LATENCY,
            latency_delay_ms=delay_ms,
            error_message="Simulated warehouse database row-lock contention",
        )
        await self._post_service(
            self._inventory_client,
            self.inventory_url,
            "/faults",
            fault.model_dump(mode="json"),
        )

        summary = await self.traffic.run_batch(count=requests, interval_sec=0.1)

        correlation_result = None
        if trigger_correlation:
            if settle_delay_sec > 0:
                await asyncio.sleep(settle_delay_sec)
            correlation_result = await self.trigger_correlation_evaluation(window_seconds=300)

        return {
            "scenario": "inventory-latency",
            "fault_injected": fault.model_dump(mode="json"),
            "traffic_summary": {
                "total_requests": summary.total_requests,
                "confirmed": summary.confirmed_count,
                "failed": summary.failed_count,
                "avg_latency_ms": summary.avg_latency_ms,
                "max_latency_ms": summary.max_latency_ms,
            },
            "correlation_result": correlation_result,
        }

    async def run_payment_error_spike(
        self,
        error_pct: float = 100.0,
        status_code: int = 502,
        requests: int = 5,
        warmup_count: int = 0,
        settle_delay_sec: float = 0.5,
        trigger_correlation: bool = True,
        reset_prior: bool = True,
    ) -> Dict[str, Any]:
        """Scenario 3: Inject payment gateway error cascade in Payment Service."""
        if reset_prior:
            await self.reset_all_faults()
        if warmup_count > 0:
            await self.run_normal_traffic(count=warmup_count, interval_sec=0.1)

        logger.info(
            "Starting Scenario 3: Payment Gateway Error Spike (%.1f%% HTTP %d for %d requests)...",
            error_pct,
            status_code,
            requests,
        )
        fault = FaultConfig(
            fault_type=FaultInjectionType.ERROR_RATE,
            error_rate_pct=error_pct,
            error_status_code=status_code,
            error_message="Stripe settlement gateway connection timeout",
        )
        await self._post_service(
            self._payment_client,
            self.payment_url,
            "/faults",
            fault.model_dump(mode="json"),
        )

        summary = await self.traffic.run_batch(count=requests, interval_sec=0.1)

        correlation_result = None
        if trigger_correlation:
            if settle_delay_sec > 0:
                await asyncio.sleep(settle_delay_sec)
            correlation_result = await self.trigger_correlation_evaluation(window_seconds=300)

        return {
            "scenario": "payment-errors",
            "fault_injected": fault.model_dump(mode="json"),
            "traffic_summary": {
                "total_requests": summary.total_requests,
                "confirmed": summary.confirmed_count,
                "failed": summary.failed_count,
                "avg_latency_ms": summary.avg_latency_ms,
                "max_latency_ms": summary.max_latency_ms,
            },
            "correlation_result": correlation_result,
        }

    async def run_payment_latency_spike(
        self,
        delay_ms: float = 800.0,
        requests: int = 5,
        warmup_count: int = 0,
        settle_delay_sec: float = 0.5,
        trigger_correlation: bool = True,
        reset_prior: bool = True,
    ) -> Dict[str, Any]:
        """Scenario 4: Inject latency spike in Payment Service causing downstream Order degradation/timeouts."""
        if reset_prior:
            await self.reset_all_faults()
        if warmup_count > 0:
            await self.run_normal_traffic(count=warmup_count, interval_sec=0.1)

        logger.info(
            "Starting Payment Latency Spike (+%.1fms delay for %d requests)...",
            delay_ms,
            requests,
        )
        fault = FaultConfig(
            fault_type=FaultInjectionType.LATENCY,
            latency_delay_ms=delay_ms,
            error_message="Simulated downstream payment gateway latency degradation",
        )
        await self._post_service(
            self._payment_client,
            self.payment_url,
            "/faults",
            fault.model_dump(mode="json"),
        )

        summary = await self.traffic.run_batch(count=requests, interval_sec=0.1)

        correlation_result = None
        if trigger_correlation:
            if settle_delay_sec > 0:
                await asyncio.sleep(settle_delay_sec)
            correlation_result = await self.trigger_correlation_evaluation(window_seconds=300)

        return {
            "scenario": "payment-latency",
            "fault_injected": fault.model_dump(mode="json"),
            "traffic_summary": {
                "total_requests": summary.total_requests,
                "confirmed": summary.confirmed_count,
                "failed": summary.failed_count,
                "avg_latency_ms": summary.avg_latency_ms,
                "max_latency_ms": summary.max_latency_ms,
            },
            "correlation_result": correlation_result,
        }

    async def run_recovery(
        self,
        count: int = 5,
        interval_sec: float = 0.15,
    ) -> Dict[str, Any]:
        """Scenario 4: Reset all faults and verify system recovery with normal traffic."""
        logger.info("Starting Scenario 4: System Recovery Verification (%d requests)...", count)
        await self.reset_all_faults()
        summary = await self.traffic.run_batch(count=count, interval_sec=interval_sec)
        return {
            "scenario": "recover",
            "traffic_summary": {
                "total_requests": summary.total_requests,
                "confirmed": summary.confirmed_count,
                "failed": summary.failed_count,
                "avg_latency_ms": summary.avg_latency_ms,
                "max_latency_ms": summary.max_latency_ms,
            },
        }

