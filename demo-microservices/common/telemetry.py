"""Reliable asynchronous telemetry reporting client for TraceMind.

Guarantees:
- Asynchronous / non-blocking dispatch so business requests never wait on telemetry.
- Bounded HTTP timeouts (default 2.0s), bounded queue capacity, and bounded retries.
- Graceful shutdown draining pending measurements within a bounded timeout.
- Strict fail-closed project discovery (never falls back to unintended projects).
- Bounded-window aggregation for error_rate (%) and request_rate (rps), preserving
  individual request latency (ms) measurements.
- Complete failure isolation: network or TraceMind outages never fail business requests.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID
import httpx
from pydantic import BaseModel, Field

from common.config import config

logger = logging.getLogger("demo_microservices.telemetry")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s]: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class TelemetryMeasurement(BaseModel):
    """Standardized measurement payload conforming to TraceMind's /anomalies/evaluate schema."""
    project_id: UUID
    service_identifier: str = Field(..., description="Service slug, e.g. order-service")
    metric_name: str = Field(..., description="Canonical metric name, e.g. latency, error_rate, request_rate")
    observed_value: float = Field(..., description="Numerical value: latency in ms, error_rate in pct, request_rate in rps")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_event_id: Optional[str] = None


class TelemetryClient:
    """Thread-safe, non-blocking telemetry emitter reporting to TraceMind's /anomalies/evaluate."""

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

        # Windowed request counters for error_rate and request_rate
        self._window_total: int = 0
        self._window_errors: int = 0
        self._window_start_monotonic: Optional[float] = None

    async def start(self) -> None:
        """Start the background telemetry dispatch and aggregation workers."""
        if not self.enabled or self._started:
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
            self._window_start_monotonic = time.monotonic()

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
        """Gracefully stop accepting measurements, drain pending items, and release resources."""
        drain_timeout = timeout if timeout is not None else self.shutdown_timeout_seconds

        async with self._lock:
            if not self._started:
                return

            # 1. Stop accepting new measurements immediately
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

            # 3. Flush any remaining partial window metrics into queue before draining
            self.flush_window(allow_while_stopping=True)

            # 4. Drain queued items up to bounded shutdown timeout
            if self._queue is not None and self._worker_task is not None:
                try:
                    await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
                    # Queue drained cleanly; signal worker to exit via sentinel
                    await self._queue.put(None)
                    await asyncio.wait_for(self._worker_task, timeout=1.0)
                except asyncio.TimeoutError:
                    self._worker_task.cancel()
                    try:
                        await self._worker_task
                    except asyncio.CancelledError:
                        pass
                    # Count and discard remaining undrained items
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
                        "TelemetryClient shutdown timeout (%.2fs) reached for '%s'; discarded %d pending measurement(s).",
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

                # Fail closed: do NOT silently fall back to projects[0]
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

    def record_request(
        self,
        latency_ms: float,
        is_error: bool,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record an individual request's latency and update bounded window counters for error_rate and request_rate."""
        if not self.enabled or self._shutting_down:
            return

        # 1. Preserve individual latency measurement per request
        self.record_latency(latency_ms, timestamp=timestamp)

        # 2. Update bounded window statistics
        if self._window_start_monotonic is None:
            self._window_start_monotonic = time.monotonic()
        self._window_total += 1
        if is_error:
            self._window_errors += 1

    def flush_window(
        self,
        now_monotonic: Optional[float] = None,
        allow_while_stopping: bool = False,
    ) -> Optional[Tuple[float, float]]:
        """Compute and enqueue aggregated error_rate (%) and request_rate (rps) for the current window.

        Returns (error_rate_pct, request_rate_rps) if requests occurred, or None if window was empty.
        """
        if not self.enabled or (self._shutting_down and not allow_while_stopping):
            return None

        now_m = now_monotonic if now_monotonic is not None else time.monotonic()
        if self._window_total == 0:
            self._window_start_monotonic = now_m
            return None

        start_m = self._window_start_monotonic if self._window_start_monotonic is not None else (
            now_m - self.aggregation_interval_seconds
        )
        elapsed_sec = max(now_m - start_m, 0.001)

        error_rate_pct = round((self._window_errors / self._window_total) * 100.0, 2)
        request_rate_rps = round(self._window_total / elapsed_sec, 2)

        # Reset window
        self._window_total = 0
        self._window_errors = 0
        self._window_start_monotonic = now_m

        self.record_error_rate(error_rate_pct, allow_while_stopping=allow_while_stopping)
        self.record_request_rate(request_rate_rps, allow_while_stopping=allow_while_stopping)
        return error_rate_pct, request_rate_rps

    def record_latency(
        self,
        latency_ms: float,
        timestamp: Optional[datetime] = None,
        allow_while_stopping: bool = False,
    ) -> bool:
        """Record execution latency in milliseconds (fire-and-forget)."""
        return self.record_measurement(
            metric_name="latency",
            observed_value=float(latency_ms),
            timestamp=timestamp,
            allow_while_stopping=allow_while_stopping,
        )

    def record_error_rate(
        self,
        error_rate_pct: float,
        timestamp: Optional[datetime] = None,
        allow_while_stopping: bool = False,
    ) -> bool:
        """Record error rate as a percentage 0.0 - 100.0 (fire-and-forget)."""
        return self.record_measurement(
            metric_name="error_rate",
            observed_value=float(error_rate_pct),
            timestamp=timestamp,
            allow_while_stopping=allow_while_stopping,
        )

    def record_request_rate(
        self,
        rps: float,
        timestamp: Optional[datetime] = None,
        allow_while_stopping: bool = False,
    ) -> bool:
        """Record request rate in requests per second (fire-and-forget)."""
        return self.record_measurement(
            metric_name="request_rate",
            observed_value=float(rps),
            timestamp=timestamp,
            allow_while_stopping=allow_while_stopping,
        )

    def record_measurement(
        self,
        metric_name: str,
        observed_value: float,
        timestamp: Optional[datetime] = None,
        source_event_id: Optional[str] = None,
        allow_while_stopping: bool = False,
    ) -> bool:
        """Queue a telemetry measurement for asynchronous background delivery.

        Returns True if accepted into queue/task, False if dropped or shutting down.
        """
        if not self.enabled:
            return False

        if self._shutting_down and not allow_while_stopping:
            logger.debug(
                "TelemetryClient shutting down; rejecting measurement %s for %s",
                metric_name,
                self.service_identifier,
            )
            return False

        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if timestamp is None:
            prev = self._last_timestamps.get(metric_name)
            if prev is not None and ts <= prev:
                ts = prev + timedelta(microseconds=1)
        self._last_timestamps[metric_name] = ts

        item = {
            "service_identifier": self.service_identifier,
            "metric_name": metric_name,
            "observed_value": float(observed_value),
            "timestamp": ts,
            "source_event_id": source_event_id,
        }

        if self._queue is not None and self._started:
            try:
                self._queue.put_nowait(item)
                return True
            except asyncio.QueueFull:
                logger.warning(
                    "Telemetry queue full (capacity %d); dropping measurement %s for %s",
                    self.queue_max_size,
                    metric_name,
                    self.service_identifier,
                )
                return False
        elif not self._shutting_down:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._send_single_item(item))
                return True
            except RuntimeError:
                return False

        return False

    async def send_measurement_direct(
        self,
        metric_name: str,
        observed_value: float,
        timestamp: Optional[datetime] = None,
        source_event_id: Optional[str] = None,
    ) -> bool:
        """Directly sends a measurement and awaits the response (useful for tests and verification).

        Guarantees failure isolation: returns False on network/backend failure without raising.
        """
        if not self.enabled:
            return False

        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if timestamp is None:
            prev = self._last_timestamps.get(metric_name)
            if prev is not None and ts <= prev:
                ts = prev + timedelta(microseconds=1)
        self._last_timestamps[metric_name] = ts

        item = {
            "service_identifier": self.service_identifier,
            "metric_name": metric_name,
            "observed_value": float(observed_value),
            "timestamp": ts,
            "source_event_id": source_event_id,
        }
        return await self._send_single_item(item)

    async def _send_single_item(self, item: Dict[str, Any]) -> bool:
        """Transmit a single measurement to TraceMind with bounded retry and failure isolation."""
        project_id = await self.ensure_project_id()
        if not project_id:
            logger.debug("Telemetry delivery skipped: project_id not resolved for slug '%s'", self.project_slug)
            return False

        payload = {
            "project_id": str(project_id),
            "service_identifier": item["service_identifier"],
            "metric_name": item["metric_name"],
            "observed_value": item["observed_value"],
            "timestamp": item["timestamp"].isoformat(),
            "source_event_id": item["source_event_id"],
        }

        url = f"{self.base_url}/anomalies/evaluate"
        client = self._http_client or httpx.AsyncClient(timeout=self.timeout)
        own_client = client != self._http_client

        attempts = 0
        max_attempts = 1 + self.max_retries

        try:
            while attempts < max_attempts:
                attempts += 1
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code in (200, 201):
                        data = resp.json()
                        if data.get("is_anomaly"):
                            logger.info(
                                "TraceMind ANOMALY DETECTED for %s:%s (value=%.2f, severity=%s)",
                                item["service_identifier"],
                                item["metric_name"],
                                item["observed_value"],
                                data.get("severity"),
                            )
                        else:
                            logger.debug(
                                "Telemetry accepted for %s:%s (value=%.2f, status=%s)",
                                item["service_identifier"],
                                item["metric_name"],
                                item["observed_value"],
                                data.get("detection_status"),
                            )
                        return True

                    if resp.status_code == 409:
                        logger.debug(
                            "Telemetry rejected (409 Conflict - out of order timestamp): %s",
                            resp.text,
                        )
                        return False

                    logger.warning(
                        "TraceMind telemetry delivery failed with status %d: %s",
                        resp.status_code,
                        resp.text,
                    )
                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as net_err:
                    if attempts >= max_attempts:
                        logger.warning(
                            "TraceMind telemetry delivery unreachable after %d attempts (%s): %s",
                            attempts,
                            url,
                            str(net_err),
                        )
                        return False
                    await asyncio.sleep(0.1)
                except Exception as unk_err:
                    logger.warning(
                        "Unexpected error during telemetry delivery to TraceMind: %s",
                        str(unk_err),
                    )
                    return False
        finally:
            if own_client:
                await client.aclose()

        return False

    async def _aggregation_loop(self) -> None:
        """Background timer flushing aggregated window metrics at a controlled interval."""
        while self._accepting:
            try:
                await asyncio.sleep(self.aggregation_interval_seconds)
                if self._accepting:
                    self.flush_window()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Aggregation loop exception: %s", str(exc))

    async def _process_queue(self) -> None:
        """Background worker loop draining the telemetry queue."""
        assert self._queue is not None
        while True:
            try:
                item = await self._queue.get()
                if item is None:
                    self._queue.task_done()
                    break
                try:
                    await self._send_single_item(item)
                except Exception as exc:
                    logger.warning("Error processing queued telemetry item: %s", str(exc))
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as loop_exc:
                logger.warning("Telemetry worker loop exception: %s", str(loop_exc))
                await asyncio.sleep(0.1)
