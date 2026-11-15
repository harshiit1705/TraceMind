"""Unit tests verifying authentication hardening and environment isolation.

Requirements verified:
1. Structured JSON test tokens ONLY accepted in test/testing environments.
2. Structured JSON test tokens rejected with 401 in development.
3. Structured JSON test tokens rejected with 401 in production.
4. Static dev tokens (e.g. tracemind-sre-token) strictly rejected in production.
5. Static dev tokens (e.g. tracemind-sre-token) work in development and test environments.
"""

import json
import pytest
from fastapi import HTTPException
from app.core.auth import authenticate_actor, OperatorRole
from app.core.config import get_settings


def test_structured_actor_in_test_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()

    payload = json.dumps({
        "actor_id": "test_sre_1",
        "name": "Hermetic SRE",
        "email": "sre@test.io",
        "role": "sre",
    })
    actor = authenticate_actor(authorization=f"Bearer {payload}")
    assert actor.actor_id == "test_sre_1"
    assert actor.role == OperatorRole.SRE


def test_structured_actor_rejected_in_dev_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    payload = json.dumps({
        "actor_id": "test_sre_1",
        "name": "Hermetic SRE",
        "role": "sre",
    })
    with pytest.raises(HTTPException) as exc_info:
        authenticate_actor(authorization=f"Bearer {payload}")
    assert exc_info.value.status_code == 401
    assert "Structured test credentials are only permitted in test environments" in exc_info.value.detail


def test_structured_actor_rejected_in_prod_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()

    payload = json.dumps({
        "actor_id": "test_sre_1",
        "name": "Hermetic SRE",
        "role": "sre",
    })
    with pytest.raises(HTTPException) as exc_info:
        authenticate_actor(authorization=f"Bearer {payload}")
    assert exc_info.value.status_code == 401


def test_static_dev_token_rejected_in_prod_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()

    for token in ["tracemind-sre-token", "tracemind-lead-sre-token", "tracemind-commander-token", "tracemind-viewer-token", "default-dev-token", "tracemind-dev-token"]:
        with pytest.raises(HTTPException) as exc_info:
            authenticate_actor(authorization=f"Bearer {token}")
        assert exc_info.value.status_code == 401
        assert "Development credentials are not permitted in production" in exc_info.value.detail


def test_static_dev_token_accepted_in_dev_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()

    actor = authenticate_actor(authorization="Bearer tracemind-sre-token")
    assert actor.role == OperatorRole.LEAD_SRE
    assert actor.name == "Alex Chen"
