"""Inventory Service (Port 8003).

Responsible for warehouse catalog lookups, stock reservation, and stock locks.
Instrumented with ObservabilityMiddleware for distributed traces, structured logs, and metrics.
"""

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status

from common.config import config
from common.middleware import ObservabilityMiddleware
from common.models import (
    FaultConfig,
    FaultInjectionType,
    InventoryItem,
    InventoryReserveRequest,
    InventoryResponse,
    InventoryStatus,
)
from common.telemetry import TelemetryClient
from common.tracing import get_current_context, start_span
from services.inventory_service.store import inventory_store

logger = logging.getLogger("demo_microservices.inventory")

telemetry = TelemetryClient(service_identifier="inventory-service")
current_fault = FaultConfig()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop the background telemetry worker."""
    await telemetry.start()
    yield
    await telemetry.stop()


app = FastAPI(
    title="TraceMind Demo - Inventory Service",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    ObservabilityMiddleware,
    service_name="inventory-service",
    telemetry_client=telemetry,
)


async def _apply_fault_injection():
    """Apply configured fault injection (latency, random error, or service outage)."""
    if current_fault.fault_type == FaultInjectionType.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=current_fault.error_message or "Inventory cluster unavailable",
        )

    if current_fault.latency_delay_ms > 0:
        await asyncio.sleep(current_fault.latency_delay_ms / 1000.0)

    if current_fault.error_rate_pct > 0:
        if random.uniform(0.0, 100.0) < current_fault.error_rate_pct:
            raise HTTPException(
                status_code=current_fault.error_status_code or 500,
                detail=current_fault.error_message or "Warehouse lock contention error",
            )


@app.get("/health", summary="Health check")
async def health_check():
    return {
        "status": "healthy",
        "service": "inventory-service",
        "port": config.INVENTORY_SERVICE_PORT,
    }


@app.get("/inventory/{sku}", response_model=InventoryItem, summary="Query item stock")
async def get_stock(sku: str):
    await _apply_fault_injection()
    item = inventory_store.get_item(sku)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item with SKU '{sku}' not found in inventory catalog",
        )
    return item


@app.post("/inventory/reserve", response_model=InventoryResponse, summary="Reserve inventory for an order")
async def reserve_inventory(req: InventoryReserveRequest):
    ctx = get_current_context()
    try:
        async with start_span(
            telemetry,
            operation_name="inventory_store.reserve",
            span_kind="internal",
            attributes={
                "order_id": req.order_id,
                "items_count": len(req.items),
                "store_type": "in_memory",
            },
        ):
            await _apply_fault_injection()
            success, reserved, err = inventory_store.reserve(req.items)

        if not success:
            if ctx:
                telemetry.record_log(
                    level="WARNING",
                    message=f"Inventory reservation rejected for order {req.order_id}: {err}",
                    request_id=ctx.request_id,
                    trace_id=ctx.trace_id,
                    span_id=ctx.span_id,
                    attributes={"order_id": req.order_id},
                )
            return InventoryResponse(
                order_id=req.order_id,
                status=InventoryStatus.OUT_OF_STOCK,
                error_message=err,
            )

        return InventoryResponse(
            order_id=req.order_id,
            status=InventoryStatus.RESERVED,
            reserved_items=reserved,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inventory reservation failed: {str(exc)}",
        )


# --- Fault Injection Control Endpoints ---

@app.get("/faults", response_model=FaultConfig, summary="Inspect current fault configuration")
async def get_fault_config():
    return current_fault


@app.post("/faults", response_model=FaultConfig, summary="Inject runtime fault")
async def set_fault_config(new_fault: FaultConfig):
    global current_fault
    current_fault = new_fault
    logger.info("Inventory Service fault updated: %s", new_fault.model_dump())
    return current_fault


@app.post("/faults/reset", response_model=FaultConfig, summary="Reset fault configuration to healthy state")
async def reset_fault_config():
    global current_fault
    current_fault = FaultConfig()
    inventory_store.reset()
    logger.info("Inventory Service faults reset to healthy baseline and catalog stock replenished")
    return current_fault


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "services.inventory_service.main:app",
        host=config.INVENTORY_SERVICE_HOST,
        port=config.INVENTORY_SERVICE_PORT,
        reload=False,
    )
