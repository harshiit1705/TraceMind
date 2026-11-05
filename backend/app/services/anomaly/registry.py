"""Service-scoped baseline registry for statistical anomaly detection.

ARCHITECTURE NOTE:
This in-memory registry provides thread-safe, process-local baseline storage for
Phase 2.3B Sprint 2. Different services and metrics maintain strictly isolated
baselines identified by the composite tuple (project_id, service_identifier, metric_name).
This in-memory store is temporary and will be replaced with persistent distributed
storage (PostgreSQL/Redis) in Phase 2.3B Sprint 3.
"""

import threading
from typing import Dict, Optional, Tuple
from uuid import UUID
from app.schemas.anomaly import AnomalyDetectionConfig
from app.services.anomaly.detector import AnomalyDetector

# Baseline composite key: (project_id, service_identifier, metric_name)
RegistryKey = Tuple[UUID, str, str]


class AnomalyBaselineRegistry:
    """Thread-safe registry for service-scoped anomaly detectors.

    Ensures that different services within the same project or across projects
    never share historical baseline samples.
    """

    def __init__(self):
        self._detectors: Dict[RegistryKey, AnomalyDetector] = {}
        self._lock = threading.RLock()

    def _normalize_key(
        self, project_id: UUID, service_identifier: str, metric_name: str
    ) -> RegistryKey:
        return (project_id, service_identifier.strip().lower(), metric_name.strip().lower())

    def get_or_create(
        self,
        project_id: UUID,
        service_identifier: str,
        metric_name: str,
        config: Optional[AnomalyDetectionConfig] = None,
    ) -> AnomalyDetector:
        """Retrieve an existing service-scoped detector or create a new one thread-safely."""
        key = self._normalize_key(project_id, service_identifier, metric_name)
        with self._lock:
            if key not in self._detectors:
                self._detectors[key] = AnomalyDetector(config=config)
            return self._detectors[key]

    def get(
        self, project_id: UUID, service_identifier: str, metric_name: str
    ) -> Optional[AnomalyDetector]:
        """Safely retrieve an existing detector without creating one if absent."""
        key = self._normalize_key(project_id, service_identifier, metric_name)
        with self._lock:
            return self._detectors.get(key)

    def reset(self, project_id: UUID, service_identifier: str, metric_name: str) -> bool:
        """Reset and remove an individual baseline for a specific service and metric."""
        key = self._normalize_key(project_id, service_identifier, metric_name)
        with self._lock:
            if key in self._detectors:
                del self._detectors[key]
                return True
            return False

    def reset_service(self, project_id: UUID, service_identifier: str) -> int:
        """Reset all metric baselines for a specific service."""
        norm_service = service_identifier.strip().lower()
        with self._lock:
            keys_to_remove = [
                k for k in self._detectors if k[0] == project_id and k[1] == norm_service
            ]
            for k in keys_to_remove:
                del self._detectors[k]
            return len(keys_to_remove)

    def reset_all(self) -> int:
        """Reset all baselines across all projects and services."""
        with self._lock:
            count = len(self._detectors)
            self._detectors.clear()
            return count

    def count(self) -> int:
        """Return total number of active metric baselines registered."""
        with self._lock:
            return len(self._detectors)


_global_registry = AnomalyBaselineRegistry()


def get_anomaly_registry() -> AnomalyBaselineRegistry:
    """Dependency injection helper returning the process-wide baseline registry."""
    return _global_registry

