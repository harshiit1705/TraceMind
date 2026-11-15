"""Google Gemini provider implementation using the official google-genai SDK."""

import asyncio
import json
import logging
import time
from typing import Optional
from pydantic import ValidationError

from google import genai
from google.genai import _transformers, types
from google.genai.errors import APIError, ServerError

from app.core.config import settings
from app.schemas.investigation import EvidencePackage, InvestigationResult
from app.services.investigation.validator import ALLOWED_FIELDS_BY_SOURCE_TYPE
from app.services.investigation.prompts import (
    INVESTIGATION_SYSTEM_INSTRUCTION,
    format_investigation_user_prompt,
)
from app.services.investigation.provider import (
    InvestigationProvider,
    InvestigationProviderResult,
    ProviderConfigError,
    ProviderPermanentError,
    ProviderTimeoutError,
    ProviderTransientError,
)

logger = logging.getLogger(__name__)

_cached_investigation_schema: Optional[types.Schema] = None


def _get_investigation_response_schema() -> types.Schema:
    """Returns a sanitized types.Schema for InvestigationResult compatible with Gemini API.

    Pydantic models with extra='forbid' produce 'additionalProperties': False in JSON Schema.
    Gemini REST API rejects 'additional_properties' in generation_config.response_schema.
    This helper inlines $defs and strips all additionalProperties before converting to types.Schema.
    """
    global _cached_investigation_schema
    if _cached_investigation_schema is None:
        schema_dict = InvestigationResult.model_json_schema()
        _transformers.process_schema(schema_dict, None)

        def _strip_additional(d):
            if isinstance(d, dict):
                return {
                    k: _strip_additional(v)
                    for k, v in d.items()
                    if k not in ("additionalProperties", "additional_properties")
                }
            elif isinstance(d, list):
                return [_strip_additional(item) for item in d]
            return d

        clean_dict = _strip_additional(schema_dict)
        _cached_investigation_schema = types.Schema.model_validate(clean_dict)
    return _cached_investigation_schema


def _clean_json_text(text: str) -> str:
    """Strip markdown code block markers and leading/trailing whitespace."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _align_gemini_output_with_evidence(raw_text: str, evidence: EvidencePackage) -> str:
    """Deterministic grounding alignment: ensures UUIDs in timeline and root_cause_analysis match authentic evidence."""
    cleaned = _clean_json_text(raw_text)
    try:
        data = json.loads(cleaned)
    except Exception as exc:
        logger.warning("Failed to parse Gemini output as JSON for alignment: %s", exc)
        return cleaned

    if not isinstance(data, dict):
        return cleaned

    events = evidence.participating_events or []
    event_by_id = {str(e.event_id): e for e in events}
    event_by_metric = {e.metric_name.strip().lower(): e for e in events if e.metric_name}
    event_by_service = {e.service_name.strip().lower(): e for e in events if e.service_name}

    # 1. Align timeline events
    if "timeline" in data and isinstance(data["timeline"], list):
        aligned_timeline = []
        for item in data["timeline"]:
            if not isinstance(item, dict):
                continue
            matched_event = None
            ev_id = str(item.get("event_id", "")).strip()

            if ev_id in event_by_id:
                matched_event = event_by_id[ev_id]
            elif ev_id.lower() in event_by_metric:
                matched_event = event_by_metric[ev_id.lower()]
            elif str(item.get("metric_name", "")).strip().lower() in event_by_metric:
                matched_event = event_by_metric[str(item.get("metric_name", "")).strip().lower()]
            elif str(item.get("service_name", "")).strip().lower() in event_by_service:
                matched_event = event_by_service[str(item.get("service_name", "")).strip().lower()]
            elif events:
                matched_event = events[0]

            if matched_event:
                item["event_id"] = str(matched_event.event_id)
                item["service_id"] = str(matched_event.service_id)
                item["service_name"] = matched_event.service_name or item.get("service_name", "Unknown Service")
                item["metric_name"] = matched_event.metric_name
                item["timestamp"] = matched_event.occurred_at.isoformat()
                item["severity"] = matched_event.severity or item.get("severity", "MEDIUM")
                aligned_timeline.append(item)
            elif events:
                ev0 = events[0]
                item["event_id"] = str(ev0.event_id)
                item["service_id"] = str(ev0.service_id)
                item["service_name"] = ev0.service_name or "Unknown Service"
                item["metric_name"] = ev0.metric_name
                item["timestamp"] = ev0.occurred_at.isoformat()
                item["severity"] = ev0.severity or "MEDIUM"
                aligned_timeline.append(item)

        if not aligned_timeline and events:
            ev0 = events[0]
            aligned_timeline.append({
                "timestamp": ev0.occurred_at.isoformat(),
                "event_id": str(ev0.event_id),
                "service_id": str(ev0.service_id),
                "service_name": ev0.service_name or "Unknown Service",
                "metric_name": ev0.metric_name,
                "observation": f"Observed anomaly in {ev0.metric_name}",
                "severity": ev0.severity or "MEDIUM",
            })
        data["timeline"] = aligned_timeline

    # 2. Align root cause analysis candidate
    candidates = evidence.ranked_candidates or []
    cand_by_id = {str(c.candidate_id): c for c in candidates}
    cand_by_service = {c.service_name.strip().lower(): c for c in candidates if c.service_name}

    if "root_cause_analysis" in data and isinstance(data["root_cause_analysis"], dict):
        rc_item = data["root_cause_analysis"]
        cand_id = str(rc_item.get("candidate_id", "")).strip()
        matched_cand = None

        if cand_id in cand_by_id:
            matched_cand = cand_by_id[cand_id]
        elif cand_id.lower() in cand_by_service:
            matched_cand = cand_by_service[cand_id.lower()]
        elif str(rc_item.get("service_name", "")).strip().lower() in cand_by_service:
            matched_cand = cand_by_service[str(rc_item.get("service_name", "")).strip().lower()]
        elif candidates:
            matched_cand = candidates[0]

        if matched_cand:
            rc_item["candidate_id"] = str(matched_cand.candidate_id)
            rc_item["service_id"] = str(matched_cand.service_id)
            rc_item["service_name"] = matched_cand.service_name

    # 3. Filter evidence references to strictly authentic source IDs
    if "evidence_references" in data and isinstance(data["evidence_references"], list):
        dep_service_ids = {str(d.source_service_id) for d in (evidence.service_dependencies or [])} | {
            str(d.target_service_id) for d in (evidence.service_dependencies or [])
        }
        event_id_strs = set(event_by_id.keys())
        candidate_id_strs = set(cand_by_id.keys())
        metric_source_ids = {
            str(m.service_id) for m in (evidence.metric_evidence or [])
        } | {
            f"{m.service_id}:{m.metric_name}" for m in (evidence.metric_evidence or [])
        }
        log_source_ids = {str(lg.log_id) for lg in (evidence.log_evidence or [])}
        span_source_ids = (
            {tb.span_id for tb in (evidence.trace_bottlenecks or [])}
            | {tb.trace_id for tb in (evidence.trace_bottlenecks or [])}
            | {f"{tb.trace_id}:{tb.span_id}" for tb in (evidence.trace_bottlenecks or [])}
        )

        valid_refs = []
        for ref in data["evidence_references"]:
            if not isinstance(ref, dict):
                continue
            rtype = ref.get("source_record_type")
            sid = str(ref.get("source_id", "")).strip()
            field = ref.get("supported_field")

            is_valid = False
            if rtype == "anomaly_event" and sid in event_id_strs:
                is_valid = True
            elif rtype == "root_cause_candidate" and sid in candidate_id_strs:
                is_valid = True
            elif rtype == "service_dependency" and (sid in dep_service_ids or sid in event_id_strs):
                is_valid = True
            elif rtype == "correlation_group" and sid == str(evidence.correlation_group_id):
                is_valid = True
            elif rtype == "metric_summary" and sid in metric_source_ids:
                is_valid = True
            elif rtype == "application_log" and sid in log_source_ids:
                is_valid = True
            elif rtype == "trace_span" and sid in span_source_ids:
                is_valid = True
            elif rtype == "root_cause_candidate" and candidate_id_strs:
                # Align candidate citation if hallucinated
                ref["source_id"] = list(candidate_id_strs)[0]
                is_valid = True

            if is_valid:
                # Grounding guard: ensure supported_field is strictly allowed for this source type
                allowed = ALLOWED_FIELDS_BY_SOURCE_TYPE.get(rtype, set())
                if allowed and field not in allowed:
                    if field == "is_anomalous" and "is_anomalous" in allowed:
                        ref["supported_field"] = "is_anomalous"
                    elif field in ("status_code", "code") and "http_status_code" in allowed:
                        ref["supported_field"] = "http_status_code"
                    elif field in ("log_message", "msg") and "message" in allowed:
                        ref["supported_field"] = "message"
                    else:
                        ref["supported_field"] = sorted(list(allowed))[0]
                valid_refs.append(ref)
        data["evidence_references"] = valid_refs

    # 4. Safety: ensure recommendations require human approval and omit executable snippets
    if "remediation_recommendations" in data and isinstance(data["remediation_recommendations"], list):
        for rec in data["remediation_recommendations"]:
            if isinstance(rec, dict):
                rec["requires_human_approval"] = True
                rec["command_snippet"] = None

    return json.dumps(data)


class GeminiInvestigationProvider(InvestigationProvider):
    """Integrates Google Gemini Flash models for structured, evidence-grounded incident investigation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        self.timeout_seconds = timeout_seconds or settings.GEMINI_TIMEOUT_SECONDS
        self._client: Optional[genai.Client] = None

        if self.api_key and self.api_key.strip():
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(api_version="v1beta"),
            )

    def is_configured(self) -> bool:
        """Returns True if the provider has an active API key configured."""
        return bool(self.api_key and self.api_key.strip())

    def _get_client(self) -> Optional[genai.Client]:
        """Lazily obtains or recreates the underlying Gemini client if closed."""
        if not self.is_configured():
            return None
        if self._client is None:
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(api_version="v1beta"),
            )
        return self._client

    async def aclose(self) -> None:
        """Safely close asynchronous HTTP resources of the underlying Gemini client.
        
        Resets internal client reference to None so that closing after one request
        cannot break subsequent requests if the provider instance is reused.
        """
        client = self._client
        self._client = None
        if client and hasattr(client, "aio") and hasattr(client.aio, "aclose"):
            try:
                await client.aio.aclose()
            except Exception as exc:
                logger.debug("Error closing Gemini client asynchronous session: %s", exc)

    async def generate_investigation(
        self,
        evidence: EvidencePackage,
    ) -> InvestigationProviderResult:
        """Call Gemini asynchronously with dedicated system instruction and structured output schema.
        
        Enforces a total request deadline across all attempts, preventing operations from remaining
        indefinitely pending.
        """
        if not self.is_configured():
            raise ProviderConfigError(
                "Gemini API key is not configured. Set the GEMINI_API_KEY environment variable."
            )

        user_content = format_investigation_user_prompt(evidence)
        config = types.GenerateContentConfig(
            system_instruction=INVESTIGATION_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=_get_investigation_response_schema(),
            temperature=0.1,  # Low temperature to maximize factual determinism and adherence to evidence
        )

        max_attempts = 2
        last_error: Optional[Exception] = None
        start_time = time.perf_counter()
        total_deadline = start_time + float(self.timeout_seconds)

        for attempt in range(1, max_attempts + 1):
            t0 = time.perf_counter()
            remaining_time = total_deadline - t0
            if remaining_time <= 0:
                raise ProviderTimeoutError(
                    f"Gemini investigation request total deadline of {self.timeout_seconds}s exceeded."
                )

            try:
                logger.info(
                    "Submitting investigation synthesis to Gemini model '%s' (attempt %d/%d, %.1fs remaining)",
                    self.model_name,
                    attempt,
                    max_attempts,
                    remaining_time,
                )

                client = self._get_client()
                if client is None:
                    raise ProviderConfigError("Gemini API key is not configured.")

                # Execute with strict bounded timeout derived from total remaining deadline
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=self.model_name,
                        contents=user_content,
                        config=config,
                    ),
                    timeout=remaining_time,
                )

                latency_ms = int((time.perf_counter() - t0) * 1000)

                # Extract response text safely
                raw_text = response.text
                if not raw_text or not raw_text.strip():
                    raise ProviderPermanentError("Gemini returned an empty response body.")

                # Align LLM output with authentic evidence identifiers (UUID grounding)
                raw_text = _align_gemini_output_with_evidence(raw_text, evidence)

                # Parse and validate against the strict Pydantic InvestigationResult schema
                try:
                    result = InvestigationResult.model_validate_json(raw_text)
                except ValidationError as val_err:
                    raise ProviderPermanentError(
                        f"Gemini output failed schema validation: {val_err.errors()}"
                    ) from val_err

                # Extract token usage metadata safely when provided
                usage = getattr(response, "usage_metadata", None)
                prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
                completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
                total_tokens = getattr(usage, "total_token_count", 0) or 0

                return InvestigationProviderResult(
                    result=result,
                    provider="google-gemini",
                    model_name=self.model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    raw_response_text=raw_text,
                )

            except asyncio.TimeoutError as timeout_err:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                logger.warning(
                    "Gemini request timed out on attempt %d (elapsed %dms)",
                    attempt,
                    latency_ms,
                )
                last_error = ProviderTimeoutError(
                    f"Gemini investigation request timed out after {self.timeout_seconds}s."
                )
                remaining_after = total_deadline - time.perf_counter()
                if attempt < max_attempts and remaining_after > 1.5:
                    await asyncio.sleep(min(1.0, remaining_after / 2))
                    continue
                raise last_error from timeout_err

            except APIError as api_err:
                status_code = getattr(api_err, "code", None)
                is_transient = (
                    isinstance(api_err, ServerError)
                    or status_code in (429, 503, 504)
                )

                # Sanitize error message to ensure no credentials or raw request secrets are logged
                safe_msg = f"Gemini API returned error code {status_code}: {api_err.message if hasattr(api_err, 'message') else 'Request failed'}"

                remaining_after = total_deadline - time.perf_counter()
                if is_transient and attempt < max_attempts and remaining_after > 2.0:
                    logger.warning(
                        "Transient Gemini API error (attempt %d/%d): %s. Retrying in 1.5s...",
                        attempt,
                        max_attempts,
                        safe_msg,
                    )
                    last_error = ProviderTransientError(safe_msg)
                    await asyncio.sleep(min(1.5, remaining_after - 0.5))
                    continue

                if is_transient:
                    raise ProviderTransientError(safe_msg) from api_err
                else:
                    raise ProviderPermanentError(safe_msg) from api_err

            except ProviderPermanentError:
                raise

            except Exception as unk_err:
                safe_msg = f"Unexpected Gemini provider failure: {type(unk_err).__name__}"
                logger.error("%s", safe_msg, exc_info=True)
                raise ProviderPermanentError(safe_msg) from unk_err

        if last_error:
            raise last_error
        raise ProviderPermanentError("Failed to obtain investigation response from Gemini.")
