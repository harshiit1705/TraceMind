"""Investigation orchestration service coordinating evidence collection, LLM synthesis, grounding validation, and persistence."""

from datetime import datetime, timezone
import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.correlation import CorrelationGroup
from app.models.investigation import Investigation
from app.schemas.investigation import GroundedInvestigationResponse
from app.services.investigation.evidence_builder import EvidenceBuilder
from app.services.investigation.gemini_provider import GeminiInvestigationProvider
from app.services.investigation.provider import (
    InvestigationProvider,
    InvestigationProviderError,
    ProviderConfigError,
    ProviderPermanentError,
    ProviderTimeoutError,
    ProviderTransientError,
)
from app.services.investigation.validator import (
    GroundingValidationError,
    validate_investigation_result_against_evidence,
)

logger = logging.getLogger(__name__)


class InvestigationServiceError(Exception):
    """Base exception for investigation service operations."""
    pass


class CorrelationGroupNotFoundError(InvestigationServiceError):
    """Raised when the specified correlation group is not found."""
    pass


class ProjectIsolationError(InvestigationServiceError):
    """Raised when an attempt is made to access a correlation group outside the authorized project."""
    pass


class InvestigationService:
    """Orchestrates end-to-end incident investigation lifecycle."""

    def __init__(
        self,
        db: Session,
        provider: Optional[InvestigationProvider] = None,
    ):
        self.db = db
        self.provider = provider or GeminiInvestigationProvider()
        self.evidence_builder = EvidenceBuilder(db)

    async def get_or_create_investigation(
        self,
        correlation_group_id: UUID,
        project_id: UUID,
        force_regenerate: bool = False,
    ) -> Investigation:
        """Coordinates the complete investigation lifecycle for a correlation group.
        
        Guarantees:
        - Strictly verifies project ownership (fails closed on mismatch).
        - Idempotently reuses existing COMPLETED investigations unless force_regenerate=True.
        - Deduplicates concurrent or in-flight (PENDING / RUNNING) investigations.
        - Persists timezone-aware UTC started_at on creation (satisfies NOT NULL constraint).
        - Grounded against real persisted telemetry via EvidenceBuilder.
        - Validates synthesized output with validate_investigation_result_against_evidence.
        - Persists FAILED with sanitized diagnostic messages without exposing secrets.
        """
        # Step A — Request validation & project scope enforcement
        # Use with_for_update on PostgreSQL for database-level concurrency protection
        group_query = (
            self.db.query(CorrelationGroup)
            .filter(CorrelationGroup.id == correlation_group_id)
        )
        if self.db.bind and getattr(self.db.bind.dialect, "name", "") == "postgresql":
            group_query = group_query.with_for_update()

        group = group_query.first()
        if not group:
            raise CorrelationGroupNotFoundError(
                f"Correlation group '{correlation_group_id}' was not found."
            )

        if group.project_id != project_id:
            # Fails closed without disclosing foreign project info
            raise ProjectIsolationError(
                f"Access denied: Correlation group '{correlation_group_id}' does not belong to authorized project."
            )

        # Step B — Idempotency: Check existing investigations
        existing_investigation = (
            self.db.query(Investigation)
            .filter(Investigation.correlation_group_id == correlation_group_id)
            .order_by(Investigation.created_at.desc())
            .first()
        )

        if existing_investigation and not force_regenerate:
            if existing_investigation.status == "COMPLETED":
                logger.info(
                    "Reusing existing COMPLETED investigation '%s' for correlation group '%s'",
                    existing_investigation.id,
                    correlation_group_id,
                )
                return existing_investigation
            elif existing_investigation.status in ("PENDING", "RUNNING"):
                logger.info(
                    "Investigation '%s' is already '%s' for correlation group '%s'; returning active record.",
                    existing_investigation.id,
                    existing_investigation.status,
                    correlation_group_id,
                )
                return existing_investigation

        # Step C — Persist PENDING with valid UTC started_at
        now_utc = datetime.now(timezone.utc)
        provider_name = getattr(self.provider, "provider_name", "google-gemini")
        model_name = getattr(self.provider, "model_name", settings.GEMINI_MODEL)
        event_count = len(group.event_associations) if group.event_associations else 0

        investigation = Investigation(
            correlation_group_id=correlation_group_id,
            incident_id=None,
            provider=provider_name,
            model_name=model_name,
            prompt_version=settings.INVESTIGATION_PROMPT_VERSION,
            schema_version=settings.INVESTIGATION_SCHEMA_VERSION,
            status="PENDING",
            agent_name="TraceMind AI Investigator",
            started_at=now_utc,
            is_demo=False,
            correlation_scope=event_count,
            spans_analyzed=0,
            confidence_score=group.confidence_score,
        )
        self.db.add(investigation)
        self.db.commit()
        self.db.refresh(investigation)

        try:
            # Step D — Build grounded evidence package scoped to authorized project
            evidence = self.evidence_builder.build_evidence_package(
                correlation_group_id=correlation_group_id,
                expected_project_id=project_id,
            )
            investigation.evidence_hash = evidence.evidence_hash

            # Step E — Mark RUNNING before calling provider
            investigation.status = "RUNNING"
            self.db.commit()
            self.db.refresh(investigation)

            # Step F — Call AI Provider (Gemini or injected mock)
            provider_result = await self.provider.generate_investigation(evidence)

            # Step G — Validate response against authentic evidence grounding
            validate_investigation_result_against_evidence(
                result=provider_result.result,
                evidence=evidence,
            )

            # Step H — Persist COMPLETED with structured payload and execution metadata
            investigation.status = "COMPLETED"
            investigation.summary = provider_result.result.incident_summary
            investigation.investigation_json = provider_result.result.model_dump(mode="json")
            investigation.prompt_tokens = provider_result.prompt_tokens
            investigation.completion_tokens = provider_result.completion_tokens
            investigation.total_tokens = provider_result.total_tokens
            investigation.latency_ms = provider_result.latency_ms
            investigation.completed_at = datetime.now(timezone.utc)
            investigation.error_message = None

            self.db.commit()
            self.db.refresh(investigation)
            logger.info(
                "Successfully generated and grounded investigation '%s' for correlation group '%s'",
                investigation.id,
                correlation_group_id,
            )
            return investigation

        except Exception as exc:
            # Step I — Persist FAILED state with sanitized error message
            self.db.rollback()
            sanitized_msg = self._sanitize_error_message(exc)
            logger.error(
                "Investigation generation failed for group '%s': %s",
                correlation_group_id,
                sanitized_msg,
                exc_info=True,
            )

            try:
                # Refresh or reload record to record failure
                inv_to_fail = (
                    self.db.query(Investigation)
                    .filter(Investigation.id == investigation.id)
                    .first()
                )
                if inv_to_fail:
                    inv_to_fail.status = "FAILED"
                    inv_to_fail.error_message = sanitized_msg
                    inv_to_fail.completed_at = datetime.now(timezone.utc)
                    self.db.commit()
                    self.db.refresh(inv_to_fail)
            except Exception as persist_err:
                logger.error("Failed to persist investigation failure status: %s", persist_err)

            raise exc
        finally:
            if hasattr(self.provider, "aclose"):
                try:
                    await self.provider.aclose()
                except Exception as close_err:
                    logger.debug("Error closing provider resources: %s", close_err)

    def get_investigation_by_id(
        self,
        investigation_id: UUID,
        expected_project_id: Optional[UUID] = None,
    ) -> Optional[Investigation]:
        """Retrieve an investigation by ID, optionally validating project ownership."""
        query = self.db.query(Investigation).filter(Investigation.id == investigation_id)
        inv = query.first()
        if not inv:
            return None

        # Verify project scope if correlation group is linked
        if expected_project_id and inv.correlation_group_id:
            group = (
                self.db.query(CorrelationGroup)
                .filter(CorrelationGroup.id == inv.correlation_group_id)
                .first()
            )
            if group and group.project_id != expected_project_id:
                raise ProjectIsolationError(
                    f"Access denied: Investigation '{investigation_id}' belongs to another project."
                )

        return inv

    def get_investigation_for_correlation_group(
        self,
        correlation_group_id: UUID,
        expected_project_id: Optional[UUID] = None,
    ) -> Optional[Investigation]:
        """Read-only retrieval of the latest persisted investigation for a correlation group.
        
        Guarantees:
        - Strictly read-only: never invokes Gemini, creates, or mutates any records.
        - Validates that the correlation group exists (raises CorrelationGroupNotFoundError if not).
        - Enforces project isolation if expected_project_id is provided (raises ProjectIsolationError).
        - Returns None if no investigation has been persisted yet.
        """
        group = (
            self.db.query(CorrelationGroup)
            .filter(CorrelationGroup.id == correlation_group_id)
            .first()
        )
        if not group:
            raise CorrelationGroupNotFoundError(
                f"Correlation group '{correlation_group_id}' was not found."
            )

        if expected_project_id and group.project_id != expected_project_id:
            raise ProjectIsolationError(
                f"Access denied: Correlation group '{correlation_group_id}' does not belong to authorized project."
            )

        latest_inv = (
            self.db.query(Investigation)
            .filter(Investigation.correlation_group_id == correlation_group_id)
            .order_by(Investigation.created_at.desc())
            .first()
        )
        return latest_inv

    def _sanitize_error_message(self, exc: Exception) -> str:
        """Strips sensitive credentials, keys, or internal stack traces from error messages."""
        if isinstance(exc, ProviderConfigError):
            return "Investigation provider configuration error: API key is not configured."
        if isinstance(exc, ProviderTransientError):
            return f"Investigation provider temporarily unavailable: {str(exc)}"
        if isinstance(exc, ProviderTimeoutError):
            return f"Investigation provider timeout: {str(exc)}"
        if isinstance(exc, GroundingValidationError):
            return f"Grounding validation error: {str(exc)}"
        if isinstance(exc, ProviderPermanentError):
            return f"Investigation provider error: {str(exc)}"
        if isinstance(exc, InvestigationProviderError):
            return f"AI provider error: {str(exc)}"
        if isinstance(exc, ProjectIsolationError):
            return "Project isolation violation."
        return f"Investigation processing error: {type(exc).__name__}"

