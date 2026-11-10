"""Order Service (Port 8001).

Primary ingress orchestrator for checkout transactions.
Orchestrates calls to Inventory Service (Port 8003) and Payment Service (Port 8002).
Reports latency and error telemetry to TraceMind via /anomalies/evaluate.
"""

import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional
from uuid import uuid4
from fastapi import FastAPI, HTTPException, status

from common.config import config
from common.models import (
    FaultConfig,
    FaultInjectionType,
    InventoryReserveRequest,
    InventoryStatus,
    OrderCreateRequest,
    OrderResponse,
    OrderStatus,
    PaymentRequest,
    PaymentStatus,
)
from common.telemetry import TelemetryClient
from services.order_service.client import DownstreamClients, DownstreamServiceError

logger = logging.getLogger("demo_microservices.order")

telemetry = TelemetryClient(service_identifier="order-service")
clients = DownstreamClients()
current_fault = FaultConfig()

# In-memory order storage
orders_db: Dict[str, OrderResponse] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop telemetry background worker and downstream HTTP connection pool."""
    await telemetry.start()
    await clients.start()
    yield
    await clients.stop()
    await telemetry.stop()


app = FastAPI(
    title="TraceMind Demo - Order Service",
    version="1.0.0",
    lifespan=lifespan,
)


async def _apply_fault_injection():
    """Apply configured fault injection on the order service layer."""
    if current_fault.fault_type == FaultInjectionType.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=current_fault.error_message or "Order Service Ingress unavailable",
        )

    # 1. Artificial Latency
    if current_fault.latency_delay_ms > 0:
        delay_sec = current_fault.latency_delay_ms / 1000.0
        await asyncio.sleep(delay_sec)

    # 2. Simulated Error Rate
    if current_fault.error_rate_pct > 0:
        roll = random.uniform(0.0, 100.0)
        if roll < current_fault.error_rate_pct:
            raise HTTPException(
                status_code=current_fault.error_status_code or 500,
                detail=current_fault.error_message or "Internal order orchestration error",
            )


@app.get("/health", summary="Health check")
async def health_check():
    return {
        "status": "healthy",
        "service": "order-service",
        "port": config.ORDER_SERVICE_PORT,
    }


@app.get("/orders", response_model=List[OrderResponse], summary="List all orders")
async def list_orders():
    return list(orders_db.values())


@app.get("/orders/{order_id}", response_model=OrderResponse, summary="Query order by ID")
async def get_order(order_id: str):
    order = orders_db.get(order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' was not found",
        )
    return order


@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED, summary="Create a new order")
async def create_order(req: OrderCreateRequest):
    start_time = time.perf_counter()
    order_id = f"ord-{uuid4().hex[:10]}"
    total_amount = round(sum(item.quantity * item.unit_price for item in req.items), 2)
    error_occurred = False
    payment_id = None

    try:
        # 1. Order Service self-check / fault injection
        await _apply_fault_injection()

        # 2. Step 1: Reserve inventory across downstream Inventory Service
        inv_resp = await clients.reserve_inventory(
            InventoryReserveRequest(order_id=order_id, items=req.items)
        )
        if inv_resp.status != InventoryStatus.RESERVED:
            error_occurred = True
            failed_order = OrderResponse(
                order_id=order_id,
                customer_id=req.customer_id,
                items=req.items,
                total_amount=total_amount,
                status=OrderStatus.FAILED,
                error_message=inv_resp.error_message or "Inventory reservation rejected",
            )
            orders_db[order_id] = failed_order
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Inventory reservation failed: {inv_resp.error_message}",
            )

        # 3. Step 2: Charge payment across downstream Payment Service
        pay_resp = await clients.charge_payment(
            PaymentRequest(
                order_id=order_id,
                customer_id=req.customer_id,
                amount=total_amount,
                payment_method=req.payment_method,
            )
        )
        if pay_resp.status != PaymentStatus.SUCCESS:
            error_occurred = True
            failed_order = OrderResponse(
                order_id=order_id,
                customer_id=req.customer_id,
                items=req.items,
                total_amount=total_amount,
                status=OrderStatus.FAILED,
                error_message=pay_resp.error_message or "Payment charge rejected",
            )
            orders_db[order_id] = failed_order
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Payment settlement failed: {pay_resp.error_message}",
            )

        payment_id = pay_resp.payment_id

        # 4. Confirmation
        confirmed_order = OrderResponse(
            order_id=order_id,
            customer_id=req.customer_id,
            items=req.items,
            total_amount=total_amount,
            status=OrderStatus.CONFIRMED,
            payment_id=payment_id,
        )
        orders_db[order_id] = confirmed_order
        return confirmed_order

    except DownstreamServiceError as down_err:
        error_occurred = True
        logger.warning("Order %s downstream failure from %s: %s", order_id, down_err.service_name, down_err.message)
        # Propagate as 502/504 Bad Gateway / Gateway Timeout reflecting distributed cascade
        http_status = status.HTTP_504_GATEWAY_TIMEOUT if down_err.status_code == 504 else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=http_status, detail=str(down_err))
    except HTTPException:
        error_occurred = True
        raise
    except Exception as exc:
        error_occurred = True
        logger.error("Unhandled exception processing order %s: %s", order_id, str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal order processing error: {str(exc)}",
        )
    finally:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        telemetry.record_request(latency_ms=elapsed_ms, is_error=error_occurred)


# --- Fault Injection Control Endpoints ---

@app.get("/faults", response_model=FaultConfig, summary="Inspect current fault configuration")
async def get_fault_config():
    return current_fault


@app.post("/faults", response_model=FaultConfig, summary="Inject runtime fault")
async def set_fault_config(new_fault: FaultConfig):
    global current_fault
    current_fault = new_fault
    logger.info("Order Service fault updated: %s", new_fault.model_dump())
    return current_fault


@app.post("/faults/reset", response_model=FaultConfig, summary="Reset fault configuration to healthy state")
async def reset_fault_config():
    global current_fault
    current_fault = FaultConfig()
    orders_db.clear()
    logger.info("Order Service faults reset to healthy baseline and orders DB cleared")
    return current_fault


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "services.order_service.main:app",
        host=config.ORDER_SERVICE_HOST,
        port=config.ORDER_SERVICE_PORT,
        reload=False,
    )

