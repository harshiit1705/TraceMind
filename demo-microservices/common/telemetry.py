"""Reliable asynchronous multi-signal telemetry client for TraceMind (Metrics, Logs, Spans).

Guarantees:
- Asynchronous / non-blocking micro-batch dispatch so business requests never wait on telemetry.
- Bounded HTTP timeouts (default 2.0s), bounded queue capacity, and bounded retries.
- Graceful shutdown draining pending metrics, logs, and spans within a bounded timeout.
- Strict fail-closed project discovery (never falls back to unintended projects).
- Single unified metric ingestion via /api/v1/telemetry/metrics (no duplicate anomaly evaluation).
- Bounded-window aggregation for error_rate (%), request_rate (rps), request_count, plus
  process CPU/memory utilization and per-request latency (ms) with endpoint/status/trace context.
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import httpx

from common.config import config

logger = logging.getLogger("demo_microservices.telemetry")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s]: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _sample_process_memory_mb() -> Optional[float]:
    """Measure current process resident memory in MB using OS/stdlib interfaces only."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return round(counters.WorkingSetSize / (1024.0 * 1024.0), 2)
        else:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                return round(rss / (1024.0 * 1024.0), 2)
            return round(rss / 1024.0, 2)
    except Exception:
        return None
    return None


class TelemetryClient:
    """Thread-safe, non-blocking multi-signal emitter shipping metrics, logs, and spans to TraceMind."""

    def __init__(
        self,
        service_identifier: str,
        base_url: Optional[str] = None,
        project_id: Optional[str] = None,
        project_slug: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        queue_max_size: Optional[int] = None,
        aggregation_interval_seconds: Optional[float] = None,
        shutdown_timeout_seconds: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        self.service_identifier = service_identifier
        self.base_url = (base_url or config.TRACEMIND_API_URL).rstrip("/")
        self._configured_project_id = project_id if project_id is not None else config.PROJECT_ID
        self.project_slug = project_slug if project_slug is not None else config.PROJECT_SLUG
        self.timeout = timeout if timeout is not None else config.TELEMETRY_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else config.TELEMETRY_MAX_RETRIES
        self.queue_max_size = (
            queue_max_size if queue_max_size is not None else config.TELEMETRY_QUEUE_MAX_SIZE
        )
        self.aggregation_interval_seconds = (
            aggregation_interval_seconds
            if aggregation_interval_seconds is not None
            else config.TELEMETRY_AGGREGATION_INTERVAL_SECONDS
        )
        self.shutdown_timeout_seconds = (
            shutdown_timeout_seconds
            if shutdown_timeout_seconds is not None
            else config.TELEMETRY_SHUTDOWN_TIMEOUT_SECONDS
        )
        self.enabled = enabled if enabled is not None else config.TELEMETRY_ENABLED

        self._resolved_project_id: Optional[UUID] = None
        self._invalid_configured_project_id: bool = False
        if self._configured_project_id:
            try:
                self._resolved_project_id = UUID(self._configured_project_id)
            except ValueError:
                self._invalid_configured_project_id = True
                logger.error(
                    "Configured PROJECT_ID '%s' is not a valid UUID; telemetry will fail closed.",
                    self._configured_project_id,
                )

        # Background worker & aggregation state
        self._queue: Optional[asyncio.Queue] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._aggregator_task: Optional[asyncio.Task] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._owns_http_client: bool = False
        self._lock = asyncio.Lock()
        self._started: bool = False
        self._accepting: bool = False
        self._shutting_down: bool = False
        self._last_timestamps: Dict[str, datetime] = {}

        # Windowed request counters + CPU sampling state
        self._window_total: int = 0
        self._window_errors: int = 0
        self._window_start_monotonic: Optional[float] = None
        self._last_cpu_time: Optional[float] = None
        self._last_wall_time: Optional[float] = None

    def _reset_stale_loop_state(self) -> None:
        """Reset worker/queue references if they belong to a closed or different event loop."""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        stale = False
        for task in (self._worker_task, self._aggregator_task):
            if task is not None:
                task_loop = task.get_loop()
                if task_loop.is_closed() or (running_loop is not None and task_loop is not running_loop):
                    stale = True
                    break

        if stale:
            self._worker_task = None
            self._aggregator_task = None
            self._queue = None
            self._started = False
            self._accepting = False
            self._shutting_down = False
            self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background telemetry dispatch and aggregation workers."""
        if not self.enabled:
            return

        self._reset_stale_loop_state()
        if self._started:
            return

        async with self._lock:
            if self._started:
                return
            self._queue = asyncio.Queue(maxsize=self.queue_max_size)
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(timeout=self.timeout)
                self._owns_http_client = True

            self._shutting_down = False
            self._accepting = True
            self._started = True
            self._window_total = 0
            self._window_errors = 0
            now_m = time.monotonic()
            self._window_start_monotonic = now_m
            self._last_wall_time = now_m
            self._last_cpu_time = time.process_time()

            self._worker_task = asyncio.create_task(self._process_queue())
            self._aggregator_task = asyncio.create_task(self._aggregation_loop())
            logger.info(
                "TelemetryClient started for '%s' targeting %s (queue_max_size=%d, window=%.2fs)",
                self.service_identifier,
                self.base_url,
                self.queue_max_size,
                self.aggregation_interval_seconds,
            )

    async def stop(self, timeout: Optional[float] = None) -> None:
        """Gracefully stop accepting telemetry, drain pending metrics/logs/spans, and clean up."""
        drain_timeout = timeout if timeout is not None else self.shutdown_timeout_seconds
        self._reset_stale_loop_state()
        if not self._started:
            return

        async with self._lock:
            if not self._started:
                return

            # 1. Stop accepting new items immediately
            self._accepting = False
            self._shutting_down = True

            # 2. Stop periodic aggregation loop
            if self._aggregator_task:
                self._aggregator_task.cancel()
                try:
                    await self._aggregator_task
                except asyncio.CancelledError:
                    pass
                self._aggregator_task = None

            # 3. Flush any remaining partial window metrics before draining
            self.flush_window(allow_while_stopping=True)

            # 4. Drain queued items up to bounded shutdown timeout
            if self._queue is not None and self._worker_task is not None:
                try:
                    await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
                    await self._queue.put(None)
                    await asyncio.wait_for(self._worker_task, timeout=1.0)
                except asyncio.TimeoutError:
                    self._worker_task.cancel()
                    try:
                        await self._worker_task
                    except asyncio.CancelledError:
                        pass
                    discarded = 0
                    while not self._queue.empty():
                        try:
                            item = self._queue.get_nowait()
                            self._queue.task_done()
                            if item is not None:
                                discarded += 1
                        except asyncio.QueueEmpty:
                            break
                    logger.warning(
                        "TelemetryClient shutdown timeout (%.2fs) reached for '%s'; discarded %d pending item(s).",
                        drain_timeout,
                        self.service_identifier,
                        discarded,
                    )
                except Exception as exc:
                    self._worker_task.cancel()
                    try:
                        await self._worker_task
                    except asyncio.CancelledError:
                        pass
                    logger.warning("Error during TelemetryClient drain for '%s': %s", self.service_identifier, str(exc))

            # 5. Close HTTP client ONLY if owned by this TelemetryClient
            if self._http_client and self._owns_http_client:
                await self._http_client.aclose()
                self._http_client = None
                self._owns_http_client = False

            self._worker_task = None
            self._queue = None
            self._started = False
            logger.info("TelemetryClient stopped for '%s'", self.service_identifier)

    async def ensure_project_id(self) -> Optional[UUID]:
        """Resolve and cache the project UUID strictly matching configured project_id or project_slug."""
        if self._configured_project_id:
            if self._invalid_configured_project_id:
                return None
            return self._resolved_project_id

        if self._resolved_project_id:
            return self._resolved_project_id

        if not self.enabled:
            return None

        url = f"{self.base_url}/projects"
        client = self._http_client or httpx.AsyncClient(timeout=self.timeout)
        own_client = client != self._http_client

        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                projects = resp.json()
                match = next((p for p in projects if p.get("slug") == self.project_slug), None)
                if match:
                    self._resolved_project_id = UUID(match["id"])
                    logger.info(
                        "Resolved TraceMind project_id: %s (slug: %s)",
                        self._resolved_project_id,
                        self.project_slug,
                    )
                    return self._resolved_project_id

                logger.error(
                    "TraceMind project with slug '%s' was not found (available: %s). "
                    "Failing closed; telemetry delivery skipped.",
                    self.project_slug,
                    [p.get("slug") for p in projects],
                )
                return None

            logger.warning(
                "TraceMind returned HTTP %d while resolving project slug '%s' from %s",
                resp.status_code,
                self.project_slug,
                url,
            )
        except Exception as exc:
            logger.warning("Failed to resolve TraceMind project_id from %s: %s", url, str(exc))
        finally:
            if own_client:
                await client.aclose()

        return None

    def _monotonic_ts(self, key: str, timestamp: Optional[datetime]) -> datetime:
        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if timestamp is None:
            prev = self._last_timestamps.get(key)
            if prev is not None and ts <= prev:
                ts = prev + timedelta(microseconds=1)
        self._last_timestamps[key] = ts
        return ts

    def _enqueue(self, signal_type: str, payload: Dict[str, Any], allow_while_stopping: bool = False) -> bool:
        if not self.enabled:
            return False
        if self._shutting_down and not allow_while_stopping:
            return False

        envelope = {"signal_type": signal_type, "payload": payload}
        if self._queue is not None and self._started:
            try:
                self._queue.put_nowait(envelope)
                return True
            except asyncio.QueueFull:
                logger.warning(
                    "Telemetry queue full (capacity %d); dropping %s item for %s",
                    self.queue_max_size,
                    signal_type,
                    self.service_identifier,
                )
                return False
        elif not self._shutting_down:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._send_batch(signal_type, [payload]))
                return True
            except RuntimeError:
                return False
        return False

    # --- Metrics Recording ---

    def record_request(
        self,
        latency_ms: float,
        is_error: bool,
        endpoint: Optional[str] = None,
        http_status_code: Optional[int] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record an individual request's latency with context and update bounded window counters."""
        if not self.enabled or self._shutting_down:
            return

        self.record_latency(
            latency_ms=latency_ms,
            endpoint=endpoint,
            http_status_code=http_status_code,
            request_id=request_id,
            trace_id=trace_id,
            timestamp=timestamp,
        )

        if self._window_start_monotonic is None:
            self._window_start_monotonic = time.monotonic()
        self._window_total += 1
        if is_error:
            self._window_errors += 1

    def flush_window(
        self,
        now_monotonic: Optional[float] = None,
        allow_while_stopping: bool = False,
    ) -> Optional[Tuple[float, Optional[float]]]:
        """Compute and enqueue aggregated error_rate (%), request_rate (rps), and request_count.

        Guards against zero/negative elapsed windows and sub-100ms shutdown micro-windows
        so partial bursts never fabricate misleading high RPS values.
        """
        if not self.enabled or (self._shutting_down and not allow_while_stopping):
            return None

        now_m = now_monotonic if now_monotonic is not None else time.monotonic()
        if self._window_total == 0:
            self._window_start_monotonic = now_m
            return None

        start_m = (
            self._window_start_monotonic
            if self._window_start_monotonic is not None
            else (now_m - self.aggregation_interval_seconds)
        )
        raw_elapsed = now_m - start_m

        # Avoid division by zero or negative elapsed intervals
        if raw_elapsed <= 0.0 and not allow_while_stopping:
            return None

        total_reqs = self._window_total
        err_reqs = self._window_errors
        error_rate_pct = round((err_reqs / total_reqs) * 100.0, 2)

        self._window_total = 0
        self._window_errors = 0
        self._window_start_monotonic = now_m

        min_rate_window_sec = 0.1
        window_seconds_attr = round(max(raw_elapsed, 0.0), 4)
        common_attrs = {
            "window_seconds": window_seconds_attr,
            "request_count": total_reqs,
            "error_count": err_reqs,
        }

        self.record_error_rate(
            error_rate_pct,
            attributes=common_attrs,
            allow_while_stopping=allow_while_stopping,
        )
        self.record_measurement(
            metric_name="request_count",
            observed_value=float(total_reqs),
            metric_unit="count",
            attributes={"window_seconds": window_seconds_attr},
            evaluate_anomaly=False,
            allow_while_stopping=allow_while_stopping,
        )

        request_rate_rps: Optional[float] = None
        if raw_elapsed >= min_rate_window_sec:
            request_rate_rps = round(total_reqs / raw_elapsed, 2)
            self.record_request_rate(
                request_rate_rps,
                attributes={"window_seconds": window_seconds_attr, "request_count": total_reqs},
                allow_while_stopping=allow_while_stopping,
            )

        return error_rate_pct, request_rate_rps

    def record_latency(
        self,
        latency_ms: float,
        endpoint: Optional[str] = None,
        http_status_code: Optional[int] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        allow_while_stopping: bool = False,
    ) -> bool:
        return self.record_measurement(
            metric_name="latency",
            observed_value=float(latency_ms),
            metric_unit="ms",
            endpoint=endpoint,
            http_status_code=http_status_code,
            request_id=request_id,
            trace_id=trace_id,
            timestamp=timestamp,
            evaluate_anomaly=True,
            allow_while_stopping=allow_while_stopping,
        )

    def record_error_rate(
        self,
        error_rate_pct: float,
        timestamp: Optional[datetime] = None,
        attributes: Optional[Dict[str, Any]] = None,
        allow_while_stopping: bool = False,
    ) -> bool:
        return self.record_measurement(
            metric_name="error_rate",
            observed_value=float(error_rate_pct),
            metric_unit="percent",
            timestamp=timestamp,
            attributes=attributes,
            evaluate_anomaly=True,
            allow_while_stopping=allow_while_stopping,
        )

    def record_request_rate(
        self,
        rps: float,
        timestamp: Optional[datetime] = None,
        attributes: Optional[Dict[str, Any]] = None,
        allow_while_stopping: bool = False,
    ) -> bool:
        return self.record_measurement(
            metric_name="request_rate",
            observed_value=float(rps),
            metric_unit="rps",
            timestamp=timestamp,
            attributes=attributes,
            evaluate_anomaly=True,
            allow_while_stopping=allow_while_stopping,
        )

    def record_measurement(
        self,
        metric_name: str,
        observed_value: float,
        timestamp: Optional[datetime] = None,
        source_event_id: Optional[str] = None,
        metric_unit: str = "",
        endpoint: Optional[str] = None,
        http_status_code: Optional[int] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        evaluate_anomaly: bool = True,
        allow_while_stopping: bool = False,
    ) -> bool:
        ts = self._monotonic_ts(f"metric:{metric_name}", timestamp)
        sample_payload = {
            "service_identifier": self.service_identifier,
            "metric_name": metric_name,
            "metric_unit": metric_unit,
            "value": float(observed_value),
            "timestamp": ts.isoformat(),
            "endpoint": endpoint,
            "http_status_code": http_status_code,
            "request_id": request_id,
            "trace_id": trace_id,
            "source_event_id": source_event_id or f"{self.service_identifier}-{metric_name}-{uuid4().hex[:12]}",
            "attributes": dict(attributes or {}),
            "evaluate_anomaly": evaluate_anomaly,
        }
        return self._enqueue("metric", sample_payload, allow_while_stopping=allow_while_stopping)

    # --- Structured Log Recording ---

    def record_log(
        self,
        level: str,
        message: str,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        exception_type: Optional[str] = None,
        exception_message: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        source_event_id: Optional[str] = None,
    ) -> bool:
        ts = self._monotonic_ts("log", timestamp)
        log_payload = {
            "service_identifier": self.service_identifier,
            "timestamp": ts.isoformat(),
            "level": level.upper(),
            "message": message[:8192],
            "request_id": request_id,
            "trace_id": trace_id,
            "span_id": span_id,
            "source_event_id": source_event_id or f"log-{uuid4().hex[:16]}",
            "attributes": dict(attributes or {}),
            "exception_type": exception_type,
            "exception_message": exception_message[:4096] if exception_message else None,
        }
        return self._enqueue("log", log_payload)

    # --- Distributed Span Recording ---

    def record_span(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str],
        operation_name: str,
        span_kind: str,
        start_time: datetime,
        end_time: datetime,
        duration_ms: float,
        status: str = "ok",
        http_status_code: Optional[int] = None,
        error_message: Optional[str] = None,
        request_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> bool:
        span_payload = {
            "service_identifier": self.service_identifier,
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "operation_name": operation_name,
            "span_kind": span_kind,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_ms": float(duration_ms),
            "status": status,
            "http_status_code": http_status_code,
            "error_message": error_message[:2048] if error_message else None,
            "request_id": request_id,
            "attributes": dict(attributes or {}),
        }
        return self._enqueue("span", span_payload)

    # --- Direct & Batch Transmission ---

    async def send_measurement_direct(
        self,
        metric_name: str,
        observed_value: float,
        timestamp: Optional[datetime] = None,
        source_event_id: Optional[str] = None,
        metric_unit: str = "",
        evaluate_anomaly: bool = True,
    ) -> bool:
        """Directly sends a single metric measurement to /telemetry/metrics and awaits response."""
        if not self.enabled:
            return False

        ts = self._monotonic_ts(f"metric:{metric_name}", timestamp)
        sample = {
            "service_identifier": self.service_identifier,
            "metric_name": metric_name,
            "metric_unit": metric_unit,
            "value": float(observed_value),
            "timestamp": ts.isoformat(),
            "source_event_id": source_event_id,
            "attributes": {},
            "evaluate_anomaly": evaluate_anomaly,
        }
        return await self._send_batch("metric", [sample])

    async def _send_batch(self, signal_type: str, items: List[Dict[str, Any]]) -> bool:
        """Transmit a batch of metrics, logs, or spans to TraceMind with bounded retry and isolation."""
        if not items:
            return True

        project_id = await self.ensure_project_id()
        if not project_id:
            logger.debug("Telemetry %s batch skipped: project_id not resolved for '%s'", signal_type, self.project_slug)
            return False

        endpoint_map = {
            "metric": ("/telemetry/metrics", {"project_id": str(project_id), "samples": items}),
            "log": ("/telemetry/logs", {"project_id": str(project_id), "logs": items}),
            "span": ("/telemetry/spans", {"project_id": str(project_id), "spans": items}),
        }
        path, body = endpoint_map[signal_type]
        url = f"{self.base_url}{path}"

        client = self._http_client or httpx.AsyncClient(timeout=self.timeout)
        own_client = client != self._http_client

        attempts = 0
        max_attempts = 1 + self.max_retries

        try:
            while attempts < max_attempts:
                attempts += 1
                try:
                    resp = await client.post(url, json=body)
                    if resp.status_code in (200, 201):
                        if signal_type == "metric":
                            data = resp.json()
                            if data.get("anomalies_detected_count", 0) > 0:
                                for r in data.get("results", []):
                                    if r.get("is_anomaly"):
                                        logger.info(
                                            "TraceMind ANOMALY DETECTED for %s:%s (severity=%s)",
                                            r.get("service_identifier"),
                                            r.get("metric_name"),
                                            r.get("anomaly_severity"),
                                        )
                        return True

                    logger.warning(
                        "TraceMind %s ingestion failed with HTTP %d (%s): %s",
                        signal_type,
                        resp.status_code,
                        url,
                        resp.text[:300],
                    )
                    if 400 <= resp.status_code < 500:
                        return False
                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as net_err:
                    if attempts >= max_attempts:
                        logger.warning(
                            "TraceMind %s ingestion unreachable after %d attempts (%s): %s",
                            signal_type,
                            attempts,
                            url,
                            str(net_err),
                        )
                        return False
                    await asyncio.sleep(0.1)
                except Exception as unk_err:
                    logger.warning("Unexpected error shipping %s batch to TraceMind: %s", signal_type, str(unk_err))
                    return False
        finally:
            if own_client:
                await client.aclose()

        return False

    def _sample_resource_metrics(self) -> None:
        """Emit process CPU% and memory RSS MB at controlled aggregation ticks."""
        now_w = time.monotonic()
        now_c = time.process_time()
        if self._last_wall_time is not None and self._last_cpu_time is not None:
            dw = now_w - self._last_wall_time
            dc = now_c - self._last_cpu_time
            if dw > 0.05:
                cpu_pct = round(max(0.0, (dc / dw) * 100.0), 2)
                self.record_measurement(
                    metric_name="cpu_usage_pct",
                    observed_value=cpu_pct,
                    metric_unit="percent",
                    evaluate_anomaly=False,
                )
        self._last_wall_time = now_w
        self._last_cpu_time = now_c

        mem_mb = _sample_process_memory_mb()
        if mem_mb is not None:
            self.record_measurement(
                metric_name="memory_usage_mb",
                observed_value=mem_mb,
                metric_unit="mb",
                evaluate_anomaly=False,
            )

    async def _aggregation_loop(self) -> None:
        """Background timer flushing windowed metrics & resource gauges at controlled interval."""
        while self._accepting:
            try:
                await asyncio.sleep(self.aggregation_interval_seconds)
                if self._accepting:
                    self.flush_window()
                    self._sample_resource_metrics()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Aggregation loop exception: %s", str(exc))

    async def _process_queue(self) -> None:
        """Background worker draining queued metrics, logs, and spans in bounded micro-batches."""
        assert self._queue is not None
        while True:
            try:
                first_item = await self._queue.get()
                if first_item is None:
                    self._queue.task_done()
                    break

                batch_items = [first_item]
                stop_after = False

                # Coalesce up to 25 queued items per tick to minimize HTTP & DB overhead
                for _ in range(24):
                    try:
                        nxt = self._queue.get_nowait()
                        if nxt is None:
                            stop_after = True
                            self._queue.task_done()
                            break
                        batch_items.append(nxt)
                    except asyncio.QueueEmpty:
                        break

                grouped: Dict[str, List[Dict[str, Any]]] = {"metric": [], "log": [], "span": []}
                for env in batch_items:
                    grouped[env["signal_type"]].append(env["payload"])

                try:
                    for sig_type, payloads in grouped.items():
                        if payloads:
                            await self._send_batch(sig_type, payloads)
                finally:
                    for _ in batch_items:
                        self._queue.task_done()

                if stop_after:
                    break
            except asyncio.CancelledError:
                break
            except Exception as loop_exc:
                logger.warning("Telemetry worker loop exception: %s", str(loop_exc))
                await asyncio.sleep(0.1)
