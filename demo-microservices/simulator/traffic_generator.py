"""Realistic traffic generator for demo e-commerce microservices."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional
import httpx

from common.config import config

logger = logging.getLogger("demo_microservices.simulator.traffic")

CATALOG_ITEMS = [
    {"sku": "SKU-LAPTOP-01", "unit_price": 1299.99},
    {"sku": "SKU-PHONE-02", "unit_price": 799.99},
    {"sku": "SKU-HEADPHONES-03", "unit_price": 199.99},
    {"sku": "SKU-KEYBOARD-04", "unit_price": 119.99},
    {"sku": "SKU-MOUSE-05", "unit_price": 59.99},
]


@dataclass
class TrafficSummary:
    """Aggregated statistics from a traffic simulation batch."""
    total_requests: int = 0
    confirmed_count: int = 0
    failed_count: int = 0
    latencies_ms: List[float] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        return round(sum(self.latencies_ms) / len(self.latencies_ms), 2) if self.latencies_ms else 0.0

    @property
    def max_latency_ms(self) -> float:
        return round(max(self.latencies_ms), 2) if self.latencies_ms else 0.0

    @property
    def requests_per_second(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return round(self.total_requests / self.duration_seconds, 2)


class TrafficGenerator:
    """Generates customer checkout requests against the Order Service."""

    def __init__(
        self,
        order_url: Optional[str] = None,
        timeout: float = 10.0,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.order_url = (order_url or config.get_order_url()).rstrip("/")
        self.timeout = timeout
        self._injected_client = http_client

    @staticmethod
    def build_random_order_payload(customer_id: Optional[str] = None) -> dict:
        """Construct a realistic randomized order payload."""
        item = random.choice(CATALOG_ITEMS)
        qty = random.randint(1, 2)
        return {
            "customer_id": customer_id or f"cust-{random.randint(1000, 9999)}",
            "items": [
                {
                    "sku": item["sku"],
                    "quantity": qty,
                    "unit_price": item["unit_price"],
                }
            ],
            "payment_method": random.choice(["credit_card", "debit_card", "apple_pay"]),
        }

    async def send_single_order(self, client: httpx.AsyncClient) -> tuple[bool, float]:
        """Issue one POST /orders request and return (is_success, elapsed_ms)."""
        payload = self.build_random_order_payload()
        t0 = time.perf_counter()
        try:
            resp = await client.post("/orders", json=payload)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if resp.status_code in (200, 201):
                return True, elapsed_ms
            logger.debug("Order failed with status %d: %s", resp.status_code, resp.text)
            return False, elapsed_ms
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.warning("Order request error: %s", str(exc))
            return False, elapsed_ms

    async def run_batch(
        self,
        count: int = 10,
        interval_sec: float = 0.2,
    ) -> TrafficSummary:
        """Execute a sequential or paced batch of customer checkout requests."""
        summary = TrafficSummary()
        client = self._injected_client or httpx.AsyncClient(
            base_url=self.order_url, timeout=self.timeout
        )
        own_client = client != self._injected_client

        batch_start = time.perf_counter()
        try:
            for i in range(count):
                ok, lat_ms = await self.send_single_order(client)
                summary.total_requests += 1
                summary.latencies_ms.append(lat_ms)
                if ok:
                    summary.confirmed_count += 1
                else:
                    summary.failed_count += 1

                if i < count - 1 and interval_sec > 0:
                    await asyncio.sleep(interval_sec)
        finally:
            summary.duration_seconds = time.perf_counter() - batch_start
            if own_client:
                await client.aclose()

        logger.info(
            "Traffic batch complete: %d reqs (%d confirmed, %d failed), avg=%.1fms, max=%.1fms, rps=%.2f",
            summary.total_requests,
            summary.confirmed_count,
            summary.failed_count,
            summary.avg_latency_ms,
            summary.max_latency_ms,
            summary.requests_per_second,
        )
        return summary

