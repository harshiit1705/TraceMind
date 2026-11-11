"""Lightweight contextvars-based distributed trace context and span helpers."""

import contextvars
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Dict, Optional
from uuid import uuid4

TRACE_ID_HEADER = "X-Trace-Id"
SPAN_ID_HEADER = "X-Span-Id"
REQUEST_ID_HEADER = "X-Request-Id"


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    request_id: str
    parent_span_id: Optional[str] = None


_trace_context_var: contextvars.ContextVar[Optional[TraceContext]] = contextvars.ContextVar(
    "tracemind_demo_trace_context",
    default=None,
)


def new_trace_id() -> str:
    return uuid4().hex


def new_span_id() -> str:
    return uuid4().hex[:16]


def new_request_id() -> str:
    return f"req-{uuid4().hex[:12]}"


def get_current_context() -> Optional[TraceContext]:
    return _trace_context_var.get()


def set_current_context(ctx: Optional[TraceContext]) -> contextvars.Token:
    return _trace_context_var.set(ctx)


def reset_current_context(token: contextvars.Token) -> None:
    _trace_context_var.reset(token)


def get_propagation_headers() -> Dict[str, str]:
    """Return HTTP propagation headers carrying the caller's currently active span."""
    ctx = get_current_context()
    if not ctx:
        return {}
    return {
        TRACE_ID_HEADER: ctx.trace_id,
        SPAN_ID_HEADER: ctx.span_id,
        REQUEST_ID_HEADER: ctx.request_id,
    }


@asynccontextmanager
async def start_span(
    telemetry_client: Any,
    operation_name: str,
    span_kind: str = "internal",
    attributes: Optional[Dict[str, Any]] = None,
):
    """Async context manager creating a child span under the active trace context."""
    parent_ctx = get_current_context()
    if parent_ctx is None:
        trace_id = new_trace_id()
        parent_span_id = None
        request_id = new_request_id()
    else:
        trace_id = parent_ctx.trace_id
        parent_span_id = parent_ctx.span_id
        request_id = parent_ctx.request_id

    span_id = new_span_id()
    child_ctx = TraceContext(
        trace_id=trace_id,
        span_id=span_id,
        request_id=request_id,
        parent_span_id=parent_span_id,
    )
    token = set_current_context(child_ctx)

    start_dt = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    status_str = "ok"
    err_msg: Optional[str] = None
    http_status: Optional[int] = None
    span_meta: Dict[str, Any] = dict(attributes or {})

    class _SpanHandle:
        def set_attribute(self, key: str, value: Any) -> None:
            span_meta[key] = value

        def set_http_status(self, code: int) -> None:
            nonlocal http_status
            http_status = code
            if code >= 500:
                nonlocal status_str
                status_str = "error"

    handle = _SpanHandle()

    try:
        yield handle
    except Exception as exc:
        status_str = "error"
        err_msg = str(exc)
        raise
    finally:
        reset_current_context(token)
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        end_dt = datetime.now(timezone.utc)
        if end_dt < start_dt:
            end_dt = start_dt
        if telemetry_client is not None:
            telemetry_client.record_span(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                operation_name=operation_name,
                span_kind=span_kind,
                start_time=start_dt,
                end_time=end_dt,
                duration_ms=duration_ms,
                status=status_str,
                http_status_code=http_status,
                error_message=err_msg,
                request_id=request_id,
                attributes=span_meta,
            )

