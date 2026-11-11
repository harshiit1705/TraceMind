"""Payment Service (Port 8002).

Responsible for processing payment authorizations, card charges, and settlement.
Instrumented with ObservabilityMiddleware for distributed traces, structured logs, and metrics.
"""

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, HTTPException, status

from common.config import config
from common.middleware import ObservabilityMiddleware
from common.models import (
    FaultConfig,
    FaultInjectionType,
    PaymentRequest,
    PaymentResponse,
    PaymentStatus,
)
from common.telemetry import TelemetryClient
from common.tracing import get_current_context, start_span

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
app.add_middleware(
    ObservabilityMiddleware,
    service_name="payment-service",
    telemetry_client=telemetry,
)


async def _apply_fault_injection():
    """Apply configured fault injection (latency, random error, or service outage)."""
    if current_fault.fault_type == FaultInjectionType.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=current_fault.error_message or "Payment settlement gateway unavailable",
        )

    if current_fault.latency_delay_ms > 0:
        await asyncio.sleep(current_fault.latency_delay_ms / 1000.0)

    if current_fault.error_rate_pct > 0:
        if random.uniform(0.0, 100.0) < current_fault.error_rate_pct:
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
    ctx = get_current_context()
    try:
        async with start_span(
            telemetry,
            operation_name="payment.gateway_charge",
            span_kind="internal",
            attributes={
                "order_id": req.order_id,
                "payment_method": req.payment_method,
                "simulated_gateway": True,
            },
        ):
            # Base realistic processing delay: ~30-45ms for card verification
            await asyncio.sleep(random.uniform(0.03, 0.045))
            await _apply_fault_injection()

        if current_fault.latency_delay_ms >= 300.0 and ctx:
            telemetry.record_log(
                level="WARNING",
                message=(
                    f"Payment gateway settlement delayed by {current_fault.latency_delay_ms:.0f}ms "
                    f"for order {req.order_id}"
                ),
                request_id=ctx.request_id,
                trace_id=ctx.trace_id,
                span_id=ctx.span_id,
                attributes={"order_id": req.order_id, "injected_delay_ms": current_fault.latency_delay_ms},
            )

        payment_id = f"pay-{uuid4().hex[:12]}"
        return PaymentResponse(
            payment_id=payment_id,
            order_id=req.order_id,
            amount=req.amount,
            status=PaymentStatus.SUCCESS,
        )
    except HTTPException as http_exc:
        if ctx:
            telemetry.record_log(
                level="ERROR",
                message=f"Payment charge failed for order {req.order_id}: {http_exc.detail}",
                request_id=ctx.request_id,
                trace_id=ctx.trace_id,
                span_id=ctx.span_id,
                attributes={"order_id": req.order_id, "status_code": http_exc.status_code},
                exception_type="PaymentGatewayHTTPException",
                exception_message=str(http_exc.detail),
            )
        raise
    except Exception as exc:
        if ctx:
            telemetry.record_log(
                level="ERROR",
                message=f"Unexpected payment error for order {req.order_id}: {str(exc)}",
                request_id=ctx.request_id,
                trace_id=ctx.trace_id,
                span_id=ctx.span_id,
                attributes={"order_id": req.order_id},
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment settlement exception: {str(exc)}",
        )


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
