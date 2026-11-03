import uuid
from datetime import datetime, timezone
from typing import List, Protocol
from uuid import UUID
from app.schemas.common import EvidenceType
from app.schemas.evidence import EvidenceResponse


class EvidenceProvider(Protocol):
    """Protocol defining the interface for retrieving incident evidence.
    Future implementations will query Prometheus, Loki, and Tempo.
    """
    def get_evidence_for_incident(self, incident_id: UUID, incident_number: str) -> List[EvidenceResponse]:
        """Fetch correlated evidence items for a given incident."""
        ...


class DemoEvidenceProvider:
    """Deterministic demonstration evidence provider for incident scenarios.
    Simulates observability evidence for INC-8492 (PostgreSQL Aurora connection pool exhaustion).
    All records are deterministically generated with stable UUIDs and timestamps.
    """

    NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

    def _generate_stable_uuid(self, incident_number: str, key: str) -> UUID:
        return uuid.uuid5(self.NAMESPACE, f"tracemind.evidence.{incident_number}.{key}")

    def get_evidence_for_incident(self, incident_id: UUID, incident_number: str) -> List[EvidenceResponse]:
        # Anchor timestamp matching October 24, 2024 at 14:18 UTC
        base_time = datetime(2024, 10, 24, 14, 18, 10, tzinfo=timezone.utc)

        if incident_number.upper() == "INC-8492":
            return [
                EvidenceResponse(
                    id=self._generate_stable_uuid("INC-8492", "ev-101-db-pool"),
                    incident_id=incident_id,
                    evidence_key="ev-101-db-pool",
                    evidence_type=EvidenceType.METRIC,
                    service_identifier="db:aurora-cluster-leader-az1",
                    title="Database Connection Pool Saturation (98%)",
                    observation="Aurora PostgreSQL active connections reached 980 out of 1,000 maximum configured limit (98.0% pool saturation threshold breach).",
                    confidence_weight=0.99,
                    timestamp=base_time,
                    payload={
                        "metric_name": "pg_stat_activity_connections_active",
                        "current_value": 980,
                        "max_connections_limit": 1000,
                        "saturation_percent": 98.0,
                        "idle_in_transaction_count": 42,
                        "longest_lock_wait_seconds": 1080,
                        "source": "simulated_prometheus_metrics",
                        "is_root_cause": True
                    },
                    is_demo=True,
                    created_at=base_time
                ),
                EvidenceResponse(
                    id=self._generate_stable_uuid("INC-8492", "ev-102-payment-latency"),
                    incident_id=incident_id,
                    evidence_key="ev-102-payment-latency",
                    evidence_type=EvidenceType.METRIC,
                    service_identifier="svc:stripe-ledger-adapter",
                    title="Payment Service P99 Latency Surge to 1,420ms",
                    observation="Payment Service P99 latency degraded from 85ms baseline to 1,420ms (+1,570% degradation) due to JDBC connection checkout timeouts.",
                    confidence_weight=0.98,
                    timestamp=datetime(2024, 10, 24, 14, 18, 32, tzinfo=timezone.utc),
                    payload={
                        "metric_name": "http_server_requests_seconds_p99",
                        "p99_latency_ms": 1420.0,
                        "baseline_latency_ms": 85.0,
                        "error_rate_percent": 8.85,
                        "tomcat_thread_pool_utilization": 94.0,
                        "source": "simulated_prometheus_metrics",
                        "is_root_cause": False
                    },
                    is_demo=True,
                    created_at=base_time
                ),
                EvidenceResponse(
                    id=self._generate_stable_uuid("INC-8492", "ev-103-order-latency"),
                    incident_id=incident_id,
                    evidence_key="ev-103-order-latency",
                    evidence_type=EvidenceType.METRIC,
                    service_identifier="svc:order-orchestration",
                    title="Order Service P99 Latency Surge to 840ms",
                    observation="Order Service checkout transactions blocked waiting on Payment Service and database locks, elevating error rate to 4.12%.",
                    confidence_weight=0.97,
                    timestamp=datetime(2024, 10, 24, 14, 18, 45, tzinfo=timezone.utc),
                    payload={
                        "metric_name": "http_server_requests_seconds_p99",
                        "p99_latency_ms": 840.0,
                        "baseline_latency_ms": 120.0,
                        "error_rate_percent": 4.12,
                        "cascade_wait_ms": 806.0,
                        "source": "simulated_prometheus_metrics",
                        "is_root_cause": False
                    },
                    is_demo=True,
                    created_at=base_time
                ),
                EvidenceResponse(
                    id=self._generate_stable_uuid("INC-8492", "ev-104-gateway-504"),
                    incident_id=incident_id,
                    evidence_key="ev-104-gateway-504",
                    evidence_type=EvidenceType.TRACE,
                    service_identifier="svc:ingress-proxy-v2",
                    title="API Gateway 504 Gateway Timeout Responses",
                    observation="Public API Gateway error rate spiked to 2.84% with HTTP 504 status codes returned on /api/v2/checkout/complete.",
                    confidence_weight=0.96,
                    timestamp=datetime(2024, 10, 24, 14, 19, 5, tzinfo=timezone.utc),
                    payload={
                        "endpoint": "POST /api/v2/checkout/complete",
                        "status_code": 504,
                        "error_rate_percent": 2.84,
                        "trace_id": "tr-9f82d4e7a1b0c",
                        "duration_ms": 8420.0,
                        "spans_count": 14,
                        "source": "simulated_tempo_traces",
                        "is_root_cause": False
                    },
                    is_demo=True,
                    created_at=base_time
                ),
                EvidenceResponse(
                    id=self._generate_stable_uuid("INC-8492", "ev-105-lock-log"),
                    incident_id=incident_id,
                    evidence_key="ev-105-lock-log",
                    evidence_type=EvidenceType.LOG,
                    service_identifier="db:aurora-cluster-leader-az1",
                    title="PostgreSQL Row Lock Contention on orders_ledger",
                    observation="PostgreSQL slow query logs show uncommitted batch transaction holding exclusive row locks on partition orders_ledger_2024_q2 for 1,080 seconds.",
                    confidence_weight=0.99,
                    timestamp=datetime(2024, 10, 24, 14, 17, 42, tzinfo=timezone.utc),
                    payload={
                        "query_signature": "SELECT * FROM orders_ledger WHERE status = 'PENDING' FOR UPDATE",
                        "lock_type": "RowExclusiveLock",
                        "blocked_pids_count": 42,
                        "lock_holder_pid": 18492,
                        "log_stream": "aurora-postgresql.log",
                        "source": "simulated_loki_logs",
                        "is_root_cause": True
                    },
                    is_demo=True,
                    created_at=base_time
                ),
                EvidenceResponse(
                    id=self._generate_stable_uuid("INC-8492", "ev-106-topology-cascade"),
                    incident_id=incident_id,
                    evidence_key="ev-106-topology-cascade",
                    evidence_type=EvidenceType.TOPOLOGY,
                    service_identifier="svc:ingress-proxy-v2",
                    title="Distributed Anomaly Propagation Path (3 Hops)",
                    observation="Topology propagation path identified: Database (Aurora) -> Payment Service -> Order Service -> API Gateway, adding +806ms cascading wait time.",
                    confidence_weight=0.95,
                    timestamp=datetime(2024, 10, 24, 14, 19, 30, tzinfo=timezone.utc),
                    payload={
                        "propagation_path": [
                            "db:aurora-cluster-leader-az1",
                            "svc:stripe-ledger-adapter",
                            "svc:order-orchestration",
                            "svc:ingress-proxy-v2"
                        ],
                        "propagation_depth_hops": 3,
                        "cascade_latency_added_ms": 806.0,
                        "source": "simulated_topology_graph",
                        "is_root_cause": False
                    },
                    is_demo=True,
                    created_at=base_time
                )
            ]

        # Generic deterministic fallback for any other incident
        return [
            EvidenceResponse(
                id=self._generate_stable_uuid(incident_number, "ev-generic-metric"),
                incident_id=incident_id,
                evidence_key=f"ev-{incident_number.lower()}-generic-metric",
                evidence_type=EvidenceType.METRIC,
                service_identifier="svc:monitored-entity",
                title=f"Telemetry Anomaly Signal for {incident_number}",
                observation=f"Demonstration anomaly detection signal registered for incident {incident_number}.",
                confidence_weight=0.85,
                timestamp=base_time,
                payload={"incident_number": incident_number, "source": "simulated_demo_provider"},
                is_demo=True,
                created_at=base_time
            )
        ]


_demo_evidence_provider = DemoEvidenceProvider()


def get_evidence_provider() -> EvidenceProvider:
    """Dependency injection provider returning the active evidence provider."""
    return _demo_evidence_provider
