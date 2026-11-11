"""Shared redaction and attribute scrubbing helpers for metrics, logs, and spans."""

from typing import Any, Dict
from app.services.investigation.evidence_builder import redact_secrets

SENSITIVE_ATTRIBUTE_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "request_body",
    "raw_body",
    "body",
    "credit_card",
    "card_number",
    "cvv",
}


def sanitize_attributes(data: Any) -> Any:
    """Recursively scrub sensitive attribute keys and secret string patterns."""
    if isinstance(data, str):
        return redact_secrets(data)
    if isinstance(data, dict):
        sanitized: Dict[str, Any] = {}
        for k, v in data.items():
            key_str = str(k)
            if key_str.strip().lower() in SENSITIVE_ATTRIBUTE_KEYS:
                sanitized[key_str] = "[REDACTED]"
            else:
                sanitized[key_str] = sanitize_attributes(v)
        return sanitized
    if isinstance(data, list):
        return [sanitize_attributes(item) for item in data]
    return data

