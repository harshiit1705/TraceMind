"""Inventory Service (Port 8003).

Responsible for warehouse catalog lookups, stock reservation, and stock locks.
Reports latency and error telemetry to TraceMind via /anomalies/evaluate.
"""

import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException, status

from common.config import config
from common.models import (
    FaultConfig,
    FaultInjectionType,
    InventoryItem,
    InventoryReserveRequest,
    InventoryResponse,
    InventoryStatus,
)
from common.telemetry import TelemetryClient
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


async def _apply_fault_injection():
    """Apply configured fault injection (latency, random error, or service outage)."""
    if current_fault.fault_type == FaultInjectionType.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=current_fault.error_message or "Inventory database cluster unavailable",
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
    start_time = time.perf_counter()
    error_occurred = False
    error_msg = None

    try:
        await _apply_fault_injection()
        success, reserved, err = inventory_store.reserve(req.items)
        if not success:
            error_occurred = True
            error_msg = err
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
        error_occurred = True
        raise
    except Exception as exc:
        error_occurred = True
        error_msg = str(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inventory reservation failed: {str(exc)}",
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

