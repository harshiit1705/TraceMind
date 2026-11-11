"""HTTP clients for Order Service downstream communication with Inventory and Payment."""

import logging
from typing import Any, Optional
import httpx

from common.config import config
from common.models import (
    InventoryReserveRequest,
    InventoryResponse,
    PaymentRequest,
    PaymentResponse,
)
from common.tracing import get_propagation_headers, start_span

logger = logging.getLogger("demo_microservices.order.client")


class DownstreamServiceError(Exception):
    """Raised when a downstream microservice fails or times out."""

    def __init__(self, service_name: str, status_code: int, message: str):
        self.service_name = service_name
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{service_name} HTTP {status_code}] {message}")


class DownstreamClients:
    """Manages HTTP clients to Inventory Service and Payment Service with trace propagation."""

    def __init__(
        self,
        inventory_url: Optional[str] = None,
        payment_url: Optional[str] = None,
        timeout: float = 5.0,
        telemetry_client: Optional[Any] = None,
    ):
        self.inventory_url = (inventory_url or config.get_inventory_url()).rstrip("/")
        self.payment_url = (payment_url or config.get_payment_url()).rstrip("/")
        self.timeout = timeout
        self.telemetry = telemetry_client
        self._inventory_client: Optional[httpx.AsyncClient] = None
        self._payment_client: Optional[httpx.AsyncClient] = None

    async def start(self):
        if self._inventory_client is None:
            self._inventory_client = httpx.AsyncClient(base_url=self.inventory_url, timeout=self.timeout)
        if self._payment_client is None:
            self._payment_client = httpx.AsyncClient(base_url=self.payment_url, timeout=self.timeout)

    async def stop(self):
        if self._inventory_client:
            await self._inventory_client.aclose()
            self._inventory_client = None
        if self._payment_client:
            await self._payment_client.aclose()
            self._payment_client = None

    async def reserve_inventory(self, req: InventoryReserveRequest) -> InventoryResponse:
        client = self._inventory_client or httpx.AsyncClient(base_url=self.inventory_url, timeout=self.timeout)
        own = client != self._inventory_client
        async with start_span(
            self.telemetry,
            operation_name="HTTP POST inventory-service /inventory/reserve",
            span_kind="client",
            attributes={"target.service": "inventory-service", "order_id": req.order_id},
        ) as span:
            headers = get_propagation_headers()
            try:
                resp = await client.post("/inventory/reserve", json=req.model_dump(mode="json"), headers=headers)
                span.set_http_status(resp.status_code)
                if resp.status_code != 200:
                    detail = resp.text
                    try:
                        detail = resp.json().get("detail", resp.text)
                    except Exception:
                        pass
                    raise DownstreamServiceError("inventory-service", resp.status_code, detail)
                return InventoryResponse(**resp.json())
            except httpx.TimeoutException:
                span.set_http_status(504)
                raise DownstreamServiceError("inventory-service", 504, "Inventory reservation timed out")
            except httpx.RequestError as exc:
                span.set_http_status(503)
                raise DownstreamServiceError("inventory-service", 503, f"Inventory unreachable: {str(exc)}")
            finally:
                if own:
                    await client.aclose()

    async def charge_payment(self, req: PaymentRequest) -> PaymentResponse:
        client = self._payment_client or httpx.AsyncClient(base_url=self.payment_url, timeout=self.timeout)
        own = client != self._payment_client
        async with start_span(
            self.telemetry,
            operation_name="HTTP POST payment-service /payments/charge",
            span_kind="client",
            attributes={"target.service": "payment-service", "order_id": req.order_id},
        ) as span:
            headers = get_propagation_headers()
            try:
                resp = await client.post("/payments/charge", json=req.model_dump(mode="json"), headers=headers)
                span.set_http_status(resp.status_code)
                if resp.status_code != 200:
                    detail = resp.text
                    try:
                        detail = resp.json().get("detail", resp.text)
                    except Exception:
                        pass
                    raise DownstreamServiceError("payment-service", resp.status_code, detail)
                return PaymentResponse(**resp.json())
            except httpx.TimeoutException:
                span.set_http_status(504)
                raise DownstreamServiceError("payment-service", 504, "Payment settlement timed out")
            except httpx.RequestError as exc:
                span.set_http_status(503)
                raise DownstreamServiceError("payment-service", 503, f"Payment service unreachable: {str(exc)}")
            finally:
                if own:
                    await client.aclose()
