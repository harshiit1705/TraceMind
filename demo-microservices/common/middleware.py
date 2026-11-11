"""FastAPI middleware instrumenting distributed traces, structured logs, and request metrics."""

from datetime import datetime, timezone
import time
from typing import Callable, Iterable, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from common.telemetry import TelemetryClient
from common.tracing import (
    REQUEST_ID_HEADER,
    SPAN_ID_HEADER,
    TRACE_ID_HEADER,
    TraceContext,
    new_request_id,
    new_span_id,
    new_trace_id,
    reset_current_context,
    set_current_context,
)

DEFAULT_EXCLUDED_PREFIXES = ("/health", "/faults", "/docs", "/redoc", "/openapi.json")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Captures incoming trace context and emits server spans, structured logs, and request metrics."""

    def __init__(
        self,
        app: ASGIApp,
        service_name: str,
        telemetry_client: TelemetryClient,
        excluded_prefixes: Iterable[str] = DEFAULT_EXCLUDED_PREFIXES,
    ):
        super().__init__(app)
        self.service_name = service_name
        self.telemetry = telemetry_client
        self.excluded_prefixes = tuple(excluded_prefixes)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path.startswith(self.excluded_prefixes):
            return await call_next(request)

        trace_id = request.headers.get(TRACE_ID_HEADER) or new_trace_id()
        parent_span_id = request.headers.get(SPAN_ID_HEADER) or None
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
        span_id = new_span_id()

        ctx = TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            request_id=request_id,
            parent_span_id=parent_span_id,
        )
        token = set_current_context(ctx)

        start_dt = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        status_code = 500
        exc_type: Optional[str] = None
        exc_msg: Optional[str] = None
        response: Optional[Response] = None

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[TRACE_ID_HEADER] = trace_id
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception as exc:
            exc_type = type(exc).__name__
            exc_msg = str(exc)
            raise
        finally:
            reset_current_context(token)
            duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            end_dt = datetime.now(timezone.utc)
            if end_dt < start_dt:
                end_dt = start_dt

            is_error = status_code >= 500 or exc_type is not None
            operation_name = f"{request.method} {path}"
            span_status = "error" if is_error else "ok"

            # Safe attributes only (no Authorization, Cookie, or raw bodies)
            safe_attrs = {
                "http.method": request.method,
                "http.path": path,
                "http.status_code": status_code,
                "duration_ms": duration_ms,
            }

            # 1. Emit server span
            self.telemetry.record_span(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                operation_name=operation_name,
                span_kind="server",
                start_time=start_dt,
                end_time=end_dt,
                duration_ms=duration_ms,
                status=span_status,
                http_status_code=status_code,
                error_message=exc_msg or (f"HTTP {status_code}" if is_error else None),
                request_id=request_id,
                attributes=safe_attrs,
            )

            # 2. Emit structured log
            if is_error:
                level = "ERROR"
                msg = f"{operation_name} failed with status {status_code} in {duration_ms:.1f}ms"
            elif duration_ms >= 500.0:
                level = "WARNING"
                msg = f"Slow request detected on {operation_name}: {duration_ms:.1f}ms (status {status_code})"
            else:
                level = "INFO"
                msg = f"{operation_name} completed with status {status_code} in {duration_ms:.1f}ms"

            self.telemetry.record_log(
                level=level,
                message=msg,
                request_id=request_id,
                trace_id=trace_id,
                span_id=span_id,
                attributes=safe_attrs,
                exception_type=exc_type,
                exception_message=exc_msg,
                timestamp=end_dt,
            )

            # 3. Emit per-request latency + update bounded window counters
            self.telemetry.record_request(
                latency_ms=duration_ms,
                is_error=is_error,
                endpoint=operation_name,
                http_status_code=status_code,
                request_id=request_id,
                trace_id=trace_id,
                timestamp=end_dt,
            )

