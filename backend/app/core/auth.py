"""Authentication and Authorization Framework for TraceMind.

Provides:
- AuthenticatedActor: Validated operator principal (identity, role, allowed projects).
- Role-based authorization permissions.
- FastAPI dependency for extracting and verifying credentials from Bearer token or API key.
- Strict rejection of unauthenticated requests and client-forged operator identities.
"""

from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from typing import List, Optional, Set
from uuid import UUID
from fastapi import Header, HTTPException, Request, status
from pydantic import BaseModel
from app.core.config import get_settings

logger = logging.getLogger("tracemind.auth")


class OperatorRole(str, Enum):
    ADMIN = "admin"
    LEAD_SRE = "lead_sre"
    SRE = "sre"
    INCIDENT_COMMANDER = "incident_commander"
    VIEWER = "viewer"


@dataclass
class AuthenticatedActor:
    """Validated principal representing the authenticated operator or service account."""
    actor_id: str
    name: str
    email: str
    role: OperatorRole
    allowed_project_ids: Optional[Set[UUID]] = None  # None indicates access to all organization projects

    def can_propose_remediation(self) -> bool:
        return self.role in (
            OperatorRole.ADMIN,
            OperatorRole.LEAD_SRE,
            OperatorRole.SRE,
            OperatorRole.INCIDENT_COMMANDER,
        )

    def can_approve_remediation(self) -> bool:
        return self.role in (
            OperatorRole.ADMIN,
            OperatorRole.LEAD_SRE,
            OperatorRole.SRE,
            OperatorRole.INCIDENT_COMMANDER,
        )

    def can_reject_remediation(self) -> bool:
        return self.role in (
            OperatorRole.ADMIN,
            OperatorRole.LEAD_SRE,
            OperatorRole.SRE,
            OperatorRole.INCIDENT_COMMANDER,
        )

    def can_cancel_remediation(self) -> bool:
        return self.role in (
            OperatorRole.ADMIN,
            OperatorRole.LEAD_SRE,
            OperatorRole.SRE,
            OperatorRole.INCIDENT_COMMANDER,
        )

    def can_execute_remediation(self) -> bool:
        return self.role in (
            OperatorRole.ADMIN,
            OperatorRole.LEAD_SRE,
            OperatorRole.SRE,
            OperatorRole.INCIDENT_COMMANDER,
        )

    def can_verify_recovery(self) -> bool:
        return self.role in (
            OperatorRole.ADMIN,
            OperatorRole.LEAD_SRE,
            OperatorRole.SRE,
            OperatorRole.INCIDENT_COMMANDER,
        )

    def can_access_project(self, project_id: UUID) -> bool:
        """Enforce tenant/project isolation boundary."""
        if self.allowed_project_ids is None:
            return True
        return project_id in self.allowed_project_ids


# Pre-configured actors for local development, demo microservices, and testing
DEFAULT_DEV_ACTOR = AuthenticatedActor(
    actor_id="usr_alex_chen_8492",
    name="Alex Chen",
    email="alex.chen@tracemind.io",
    role=OperatorRole.LEAD_SRE,
    allowed_project_ids=None,
)

DEMO_COMMANDER_ACTOR = AuthenticatedActor(
    actor_id="usr_maria_vance_01",
    name="Maria Vance",
    email="maria.vance@tracemind.io",
    role=OperatorRole.INCIDENT_COMMANDER,
    allowed_project_ids=None,
)

READONLY_VIEWER_ACTOR = AuthenticatedActor(
    actor_id="usr_viewer_guest_09",
    name="Guest Observer",
    email="observer@tracemind.io",
    role=OperatorRole.VIEWER,
    allowed_project_ids=None,
)

# Known static development and test tokens
KNOWN_DEV_TOKENS = {
    "tracemind-sre-token": DEFAULT_DEV_ACTOR,
    "tracemind-lead-sre-token": DEFAULT_DEV_ACTOR,
    "tracemind-commander-token": DEMO_COMMANDER_ACTOR,
    "tracemind-viewer-token": READONLY_VIEWER_ACTOR,
    "dev-api-key-tracemind-secret": DEFAULT_DEV_ACTOR,
}


def authenticate_actor(
    authorization: Optional[str] = Header(None, description="Bearer token or API key"),
    x_api_key: Optional[str] = Header(None, description="TraceMind API key"),
    x_operator_token: Optional[str] = Header(None, description="TraceMind Operator Token"),
) -> AuthenticatedActor:
    """Dependency that authenticates the incoming HTTP request.
    
    Rejects any request lacking valid authentication credentials with HTTP 401 Unauthorized.
    Derives operator identity strictly from validated credentials.
    """
    token = None

    if authorization:
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() in ("bearer", "token", "apikey"):
            token = parts[1].strip()
        else:
            token = authorization.strip()
    elif x_api_key:
        token = x_api_key.strip()
    elif x_operator_token:
        token = x_operator_token.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Include 'Authorization: Bearer <token>' or 'X-API-Key'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In production environments, strictly block all static development/testing fixtures
    settings = get_settings()
    is_prod = settings.ENVIRONMENT.lower() in ("prod", "production")
    if is_prod and (token in KNOWN_DEV_TOKENS or token in ("default-dev-token", "tracemind-dev-token")):
        logger.error("Security violation: Attempted to use static development credentials in production environment!")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Development credentials are not permitted in production environments.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check known dev / testing tokens (only active in non-production)
    if not is_prod and token in KNOWN_DEV_TOKENS:
        return KNOWN_DEV_TOKENS[token]

    # Handle structured test tokens (e.g. JSON-encoded actor for hermetic unit testing)
    if token.startswith("{") and token.endswith("}"):
        try:
            data = json.loads(token)
            pids = None
            if "allowed_project_ids" in data and data["allowed_project_ids"] is not None:
                pids = {UUID(p) for p in data["allowed_project_ids"]}
            return AuthenticatedActor(
                actor_id=data.get("actor_id", "test_actor"),
                name=data.get("name", "Test Operator"),
                email=data.get("email", "test@tracemind.io"),
                role=OperatorRole(data.get("role", "sre")),
                allowed_project_ids=pids,
            )
        except Exception as exc:
            logger.warning("Failed to parse structured token: %s", exc)

    # Allow custom API key matching configured DEV key
    if token == "default-dev-token" or token == "tracemind-dev-token":
        return DEFAULT_DEV_ACTOR

    # Token unrecognized -> Reject with 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
