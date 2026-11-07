"""Google Gemini provider implementation using the official google-genai SDK."""

import asyncio
import logging
import time
from typing import Optional
from pydantic import ValidationError

from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError

from app.core.config import settings
from app.schemas.investigation import EvidencePackage, InvestigationResult
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


class GeminiInvestigationProvider(InvestigationProvider):
    """Integrates Google Gemini Flash models for structured, evidence-grounded incident investigation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        self.timeout_seconds = timeout_seconds or settings.GEMINI_TIMEOUT_SECONDS
        self._client: Optional[genai.Client] = None

        if self.api_key and self.api_key.strip():
            self._client = genai.Client(api_key=self.api_key)

    def is_configured(self) -> bool:
        """Returns True if the provider has an active API key configured."""
        return bool(self.api_key and self.api_key.strip())

    def _get_client(self) -> Optional[genai.Client]:
        """Lazily obtains or recreates the underlying Gemini client if closed."""
        if not self.is_configured():
            return None
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
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
            response_schema=InvestigationResult,
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
