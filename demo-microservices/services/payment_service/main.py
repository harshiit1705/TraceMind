"""Payment Service (Port 8002).

Responsible for processing payment authorizations, card charges, and settlement.
Reports latency and error telemetry to TraceMind via /anomalies/evaluate.
"""

import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, HTTPException, status

from common.config import config
from common.models import (
    FaultConfig,
    FaultInjectionType,
    PaymentRequest,
    PaymentResponse,
    PaymentStatus,
)
from common.telemetry import TelemetryClient

logger = logging.getLogger("demo_microservices.payment")

telemetry = TelemetryClient(service_identifier="payment-service")
current_fault = FaultConfig()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop the background telemetry worker."""
    await telemetry.start()
    yield
    await telemetry.stop()


app = FastAPI(
    title="TraceMind Demo - Payment Service",
    version="1.0.0",
    lifespan=lifespan,
)


async def _apply_fault_injection():
    """Apply configured fault injection (latency, random error, or service outage)."""
    if current_fault.fault_type == FaultInjectionType.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=current_fault.error_message or "Payment settlement gateway unavailable",
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
                status_code=current_fault.error_status_code or 502,
                detail=current_fault.error_message or "Payment processor connection timeout",
            )


@app.get("/health", summary="Health check")
async def health_check():
    return {
        "status": "healthy",
        "service": "payment-service",
        "port": config.PAYMENT_SERVICE_PORT,
    }


@app.post("/payments/charge", response_model=PaymentResponse, summary="Process payment charge for an order")
async def charge_payment(req: PaymentRequest):
    start_time = time.perf_counter()
    error_occurred = False
    error_msg = None

    try:
        # Base realistic processing delay: ~30-45ms for card verification
        await asyncio.sleep(random.uniform(0.03, 0.045))
        await _apply_fault_injection()

        payment_id = f"pay-{uuid4().hex[:12]}"
        return PaymentResponse(
            payment_id=payment_id,
            order_id=req.order_id,
            amount=req.amount,
            status=PaymentStatus.SUCCESS,
        )
    except HTTPException as http_exc:
        error_occurred = True
        error_msg = str(http_exc.detail)
        raise
    except Exception as exc:
        error_occurred = True
        error_msg = str(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment settlement exception: {str(exc)}",
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
    logger.info("Payment Service fault updated: %s", new_fault.model_dump())
    return current_fault


@app.post("/faults/reset", response_model=FaultConfig, summary="Reset fault configuration to healthy state")
async def reset_fault_config():
    global current_fault
    current_fault = FaultConfig()
    logger.info("Payment Service faults reset to healthy baseline")
    return current_fault


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "services.payment_service.main:app",
        host=config.PAYMENT_SERVICE_HOST,
        port=config.PAYMENT_SERVICE_PORT,
        reload=False,
    )

