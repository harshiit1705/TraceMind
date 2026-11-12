"""Remediation execution adapters: real microservice calls and safe simulated actions."""

import logging
from typing import Any, Dict
import httpx

from app.schemas.recommendation import AllowlistedAction, RemediationExecutionMode
from app.services.remediation.exceptions import (
    ActionNotAllowlistedError,
    ParameterValidationError,
    RemediationExecutionError,
    RemediationTimeoutError,
)

logger = logging.getLogger(__name__)

# Service port registry for demo microservices
DEMO_SERVICE_PORTS = {
    "inventory-service": 8003,
    "inventory": 8003,
    "payment-service": 8002,
    "payment": 8002,
    "order-service": 8001,
    "order": 8001,
}


def normalize_service_name(service_name: str) -> str:
    """Normalize service name variations to standard identifiers."""
    s = (service_name or "").lower().strip()
    if "inventory" in s:
        return "inventory-service"
    if "payment" in s:
        return "payment-service"
    if "order" in s:
        return "order-service"
    return s


class RealMicroserviceExecutionAdapter:
    """Executes safe, verified HTTP actions against running demo microservices."""

    TIMEOUT_SECONDS = 3.0

    @classmethod
    def can_handle(cls, action_name: str, target_service: str) -> bool:
        normalized_service = normalize_service_name(target_service)
        normalized_action = (action_name or "").upper().strip()
        is_supported_action = normalized_action in (
            AllowlistedAction.RESET_SERVICE_FAULTS.value,
            AllowlistedAction.RESTART_SERVICE.value,
        )
        return is_supported_action and normalized_service in DEMO_SERVICE_PORTS

    @classmethod
    def execute(
        cls,
        action_name: str,
        target_service: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_service = normalize_service_name(target_service)
        port = DEMO_SERVICE_PORTS.get(normalized_service)
        if not port:
            raise RemediationExecutionError(
                f"Target service '{target_service}' does not map to a recognized demo microservice port."
            )

        base_url = f"http://127.0.0.1:{port}"
        reset_endpoint = f"{base_url}/faults/reset"
        health_endpoint = f"{base_url}/health"

        timeout = httpx.Timeout(connect=0.2, read=2.0, write=2.0, pool=0.5)
        try:
            with httpx.Client(timeout=timeout) as client:
                # Step 1: Execute fault reset
                try:
                    resp = client.post(reset_endpoint)
                    if resp.status_code != 200:
                        raise RemediationExecutionError(
                            f"Target service {normalized_service} returned HTTP {resp.status_code} during reset: {resp.text}"
                        )
                except httpx.TimeoutException as exc:
                    raise RemediationTimeoutError(
                        f"Execution timed out after {cls.TIMEOUT_SECONDS}s calling {reset_endpoint}"
                    ) from exc
                except httpx.RequestError as exc:
                    raise RemediationExecutionError(
                        f"Network error connecting to {reset_endpoint}: {str(exc)}"
                    ) from exc

                # Step 2: Confirm healthy state
                try:
                    health_resp = client.get(health_endpoint)
                    if health_resp.status_code != 200:
                        raise RemediationExecutionError(
                            f"Health verification failed for {normalized_service}: HTTP {health_resp.status_code}"
                        )
                    health_data = health_resp.json()
                    if health_data.get("status") != "healthy":
                        raise RemediationExecutionError(
                            f"Health verification failed for {normalized_service}: status is '{health_data.get('status')}'"
                        )
                except httpx.TimeoutException as exc:
                    raise RemediationTimeoutError(
                        f"Health check timed out after {cls.TIMEOUT_SECONDS}s calling {health_endpoint}"
                    ) from exc
                except httpx.RequestError as exc:
                    raise RemediationExecutionError(
                        f"Network error verifying health at {health_endpoint}: {str(exc)}"
                    ) from exc

        except (RemediationExecutionError, RemediationTimeoutError):
            raise
        except Exception as unk_exc:
            raise RemediationExecutionError(f"Unexpected error communicating with {normalized_service}: {unk_exc}") from unk_exc

        return {
            "execution_mode": RemediationExecutionMode.REAL.value,
            "is_simulated": False,
            "target_service": normalized_service,
            "action": action_name,
            "endpoint": reset_endpoint,
            "health_endpoint": health_endpoint,
            "status_code": 200,
            "health_status": "healthy",
            "verified": True,
            "message": f"Successfully reset runtime faults on {normalized_service} and verified healthy state.",
        }


class SimulatedExecutionAdapter:
    """Safely executes and validates simulated infrastructure actions for local development and testing."""

    @classmethod
    def execute(
        cls,
        action_name: str,
        target_service: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_action = (action_name or "").upper().strip()

        if normalized_action == AllowlistedAction.SCALE_REPLICAS.value:
            replica_count = parameters.get("replica_count", 3)
            try:
                replica_count = int(replica_count)
            except (ValueError, TypeError):
                raise ParameterValidationError("Parameter 'replica_count' must be an integer.")

            if replica_count < 1 or replica_count > 10:
                raise ParameterValidationError("Parameter 'replica_count' must be between 1 and 10.")

            return {
                "execution_mode": RemediationExecutionMode.SIMULATED.value,
                "is_simulated": True,
                "target_service": target_service,
                "action": normalized_action,
                "replica_count": replica_count,
                "previous_replicas": 1,
                "verified": True,
                "simulation_notes": f"Simulated horizontal scaling applied to {target_service}. Replicas adjusted to {replica_count}.",
            }

        elif normalized_action == AllowlistedAction.ROLLBACK_DEPLOYMENT.value:
            target_version = parameters.get("target_version", "v1.0.0")
            if not isinstance(target_version, str) or not target_version.strip():
                raise ParameterValidationError("Parameter 'target_version' must be a non-empty string.")

            return {
                "execution_mode": RemediationExecutionMode.SIMULATED.value,
                "is_simulated": True,
                "target_service": target_service,
                "action": normalized_action,
                "target_version": target_version.strip(),
                "verified": True,
                "simulation_notes": f"Simulated deployment rollback applied to {target_service} targeting version {target_version}.",
            }

        elif normalized_action == AllowlistedAction.FLUSH_CONNECTION_POOL.value:
            return {
                "execution_mode": RemediationExecutionMode.SIMULATED.value,
                "is_simulated": True,
                "target_service": target_service,
                "action": normalized_action,
                "verified": True,
                "simulation_notes": f"Connection pool flushed for {target_service}. Idle connections closed and pool metrics reset.",
            }

        elif normalized_action == AllowlistedAction.DRAIN_TRAFFIC.value:
            drain_pct = parameters.get("drain_percentage", 50)
            try:
                drain_pct = float(drain_pct)
            except (ValueError, TypeError):
                raise ParameterValidationError("Parameter 'drain_percentage' must be a valid number.")

            if drain_pct < 0.0 or drain_pct > 100.0:
                raise ParameterValidationError("Parameter 'drain_percentage' must be between 0.0 and 100.0.")

            return {
                "execution_mode": RemediationExecutionMode.SIMULATED.value,
                "is_simulated": True,
                "target_service": target_service,
                "action": normalized_action,
                "drain_percentage": drain_pct,
                "verified": True,
                "simulation_notes": f"Traffic drained by {drain_pct}% from {target_service} pods.",
            }

        elif normalized_action in (
            AllowlistedAction.RESET_SERVICE_FAULTS.value,
            AllowlistedAction.RESTART_SERVICE.value,
        ):
            # Safe simulated execution for offline environments or unit tests
            return {
                "execution_mode": RemediationExecutionMode.SIMULATED.value,
                "is_simulated": True,
                "target_service": target_service,
                "action": normalized_action,
                "verified": True,
                "simulation_notes": f"Simulated reset/restart applied to {target_service} in offline development mode.",
            }

        else:
            raise ActionNotAllowlistedError(
                f"Action '{action_name}' is not an approved allowlisted remediation action."
            )
