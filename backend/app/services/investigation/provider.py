"""Abstract provider interface and result containers for incident investigation synthesis."""

from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.schemas.investigation import EvidencePackage, InvestigationResult


class InvestigationProviderResult(BaseModel):
    """Container holding synthesized investigation result and execution metadata."""
    model_config = ConfigDict(extra="forbid")

    result: InvestigationResult
    provider: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    raw_response_text: Optional[str] = None


class InvestigationProviderError(Exception):
    """Base exception for investigation provider errors."""
    pass


class ProviderConfigError(InvestigationProviderError):
    """Raised when provider configuration or credentials are missing/invalid."""
    pass


class ProviderTimeoutError(InvestigationProviderError):
    """Raised when provider call times out."""
    pass


class ProviderTransientError(InvestigationProviderError):
    """Raised on transient network or rate-limit errors (HTTP 429, 503)."""
    pass


class ProviderPermanentError(InvestigationProviderError):
    """Raised on non-retryable errors (malformed schema, auth failure, bad request)."""
    pass


class InvestigationProvider(ABC):
    """Abstract interface defining the contract for AI investigation providers."""

    @abstractmethod
    async def generate_investigation(
        self,
        evidence: EvidencePackage,
    ) -> InvestigationProviderResult:
        """Synthesize a structured InvestigationResult grounded in the supplied EvidencePackage."""
        raise NotImplementedError

