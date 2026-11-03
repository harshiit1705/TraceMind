# TraceMind API Contracts (Phase 2.3A)

Base URL: `http://localhost:8000/api/v1`

Interactive API Docs:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

---

## 1. Health & System Probes

### `GET /api/v1/health`
Liveness probe indicating the backend application is running.

**Response `200 OK`**:
```json
{
  "status": "healthy",
  "service": "TraceMind API",
  "version": "0.2.3a",
  "timestamp": "2026-11-02T15:30:00.000000Z",
  "demo_mode": true
}
```

### `GET /api/v1/ready`
Readiness probe verifying active database connectivity (`SELECT 1`).

**Response `200 OK`**:
```json
{
  "status": "ready",
  "database": "connected",
  "timestamp": "2026-11-02T15:30:00.000000Z"
}
```
**Response `503 Service Unavailable`** (if database cannot be contacted):
```json
{
  "detail": "Database connectivity check failed: could not connect to server"
}
```

---

## 2. Projects & Organizations

### `GET /api/v1/projects`
List all projects for the active tenant.

**Response `200 OK`**:
```json
[
  {
    "id": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
    "organization_id": "9f8e7d6c-5b4a-3a2b-1c0d-9e8f7a6b5c4d",
    "name": "Core E-Commerce & Payments",
    "slug": "core-ecommerce",
    "environment": "production",
    "description": "Mission-critical distributed payment settlement and checkout processing fleet.",
    "is_demo": true,
    "created_at": "2024-10-24T14:00:00Z",
    "updated_at": "2024-10-24T14:00:00Z"
  }
]
```

### `GET /api/v1/projects/{project_id}/services`
List all microservices registered to a specific project.

**Parameters**:
- `project_id` (Path, UUID): Project unique identifier.

**Response `200 OK`**:
```json
[
  {
    "id": "2b3c4d5e-6f7a-8b9c-0d1e-2f3a4b5c6d7e",
    "project_id": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
    "name": "Payment Service",
    "slug": "payment-service",
    "identifier": "svc:stripe-ledger-adapter",
    "tier": 0,
    "owner_team": "Payments Engine",
    "status": "degraded",
    "request_rate_rps": 3110.0,
    "error_rate_percent": 8.85,
    "p95_latency_ms": 1420.0,
    "metadata_json": {
      "last_deployment": "v3.1.0 (3 days ago by @elena)",
      "availability_percent": 94.8,
      "cpu_saturation_percent": 94,
      "memory_usage_percent": 89
    },
    "created_at": "2024-10-24T14:00:00Z",
    "updated_at": "2024-10-24T14:00:00Z"
  }
]
```

---

## 3. Services Registry

### `GET /api/v1/services`
Query the service catalog with optional multi-attribute filters.

**Query Parameters**:
- `project_id` (Query, Optional, UUID): Filter by project ID.
- `status` (Query, Optional, string): `healthy`, `degraded`, or `unhealthy`.
- `tier` (Query, Optional, integer): Tier level (`0`, `1`, `2`).

---

## 4. Incidents Command Center

### `GET /api/v1/incidents`
Retrieve paginated list of incidents.

**Query Parameters**:
- `project_id` (Query, Optional, UUID): Filter by project.
- `status` (Query, Optional, string): `INVESTIGATING`, `ACKNOWLEDGED`, `MITIGATED`, `RESOLVED`.
- `severity` (Query, Optional, string): `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`.
- `limit` (Query, Optional, int, default 20, max 100): Items per page.
- `offset` (Query, Optional, int, default 0): Item offset.

**Response `200 OK`**:
```json
{
  "items": [
    {
      "id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
      "project_id": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
      "incident_number": "INC-8492",
      "title": "Database connection pool exhaustion causing cascading payment & checkout timeouts",
      "severity": "CRITICAL",
      "status": "INVESTIGATING",
      "started_at": "2024-10-24T14:18:00Z",
      "mitigated_at": null,
      "resolved_at": null,
      "commander_name": "Alex Chen",
      "commander_role": "Staff SRE",
      "root_cause_summary": "Zombie idle transactions holding exclusive row locks on orders_ledger partition",
      "affected_services": [
        "API Gateway",
        "Order Service",
        "Payment Service",
        "PostgreSQL Primary (Aurora)"
      ],
      "summary": "Continuous transactions held row-level exclusive locks against partition orders_ledger_2024_q2, exhausting max connections within 180s.",
      "is_demo": true,
      "created_at": "2024-10-24T14:18:00Z",
      "updated_at": "2024-10-24T14:18:00Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

### `GET /api/v1/incidents/{incident_id}`
Retrieve incident details by UUID or human-readable number (e.g. `INC-8492`).

### `GET /api/v1/incidents/{incident_id}/timeline`
Retrieve chronological audit events and state transitions.

**Response `200 OK`**:
```json
{
  "incident_id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
  "incident_number": "INC-8492",
  "events": [
    {
      "id": "5a6b7c8d-9e0f-1a2b-3c4d-5e6f7a8b9c0d",
      "incident_id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
      "timestamp": "2024-10-24T14:17:42Z",
      "title": "orders_ledger Lock Contention Detected",
      "event_type": "anomaly",
      "source": "Loki Log Stream",
      "description": "Exclusive row lock held by 42 zombie backend PID threads on partition orders_ledger_2024_q2.",
      "payload": {}
    }
  ]
}
```

---

## 5. Correlated Telemetry Evidence

### `GET /api/v1/incidents/{incident_id}/evidence`
Retrieve correlated multi-modal evidence (metrics, logs, traces, topology).

**Response `200 OK`**:
```json
{
  "incident_id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
  "incident_number": "INC-8492",
  "total_count": 6,
  "is_demo_scenario": true,
  "items": [
    {
      "id": "3f4a5b6c-7d8e-9f0a-1b2c-3d4e5f6a7b8c",
      "incident_id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
      "evidence_type": "metric",
      "service_identifier": "db:aurora-cluster-leader-az1",
      "title": "Database Connection Pool Saturation (98%)",
      "observation": "Aurora PostgreSQL active connections reached 980 out of 1,000 maximum configured limit (98.0% pool saturation threshold breach).",
      "confidence_weight": 0.99,
      "timestamp": "2024-10-24T14:18:10Z",
      "payload": {
        "metric_name": "pg_stat_activity_connections_active",
        "current_value": 980,
        "max_connections_limit": 1000,
        "saturation_percent": 98.0,
        "idle_in_transaction_count": 42,
        "longest_lock_wait_seconds": 1080,
        "source": "simulated_prometheus_metrics",
        "is_root_cause": true
      },
      "is_demo": true,
      "created_at": "2024-10-24T14:18:10Z"
    }
  ]
}
```

---

## 6. Autonomous Investigation Contracts

### `GET /api/v1/investigations/{investigation_id}`
Retrieve root-cause analysis findings and safe remediation recommendations.

**Response `200 OK`**:
```json
{
  "id": "8a9b0c1d-2e3f-4a5b-6c7d-8e9f0a1b2c3d",
  "incident_id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
  "agent_name": "Autonomous Agent #4",
  "status": "COMPLETED",
  "summary": "Autonomous investigation correlated database connection pool exhaustion with zombie transaction row locks.",
  "correlation_scope": 42,
  "spans_analyzed": 128400,
  "confidence_score": 94.0,
  "is_demo": true,
  "started_at": "2024-10-24T14:18:10Z",
  "completed_at": "2024-10-24T14:33:10Z",
  "findings": [
    {
      "id": "1b2c3d4e-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
      "investigation_id": "8a9b0c1d-2e3f-4a5b-6c7d-8e9f0a1b2c3d",
      "rank": 1,
      "title": "Zombie idle transactions holding locks on orders_ledger partition",
      "probable_root_cause": "Uncommitted batch cron job held row-level exclusive locks against orders_ledger partition, starving JDBC connection pool.",
      "explanation": "pg_stat_activity records show 42 backend threads blocked waiting on PID 18492 for >1,080 seconds.",
      "status": "CONFIRMED",
      "confidence_score": 94.0,
      "affected_services": [
        "PostgreSQL Primary (Aurora)",
        "Payment Service",
        "Order Service"
      ],
      "supporting_evidence_ids": [
        "ev-101-db-pool",
        "ev-105-lock-log"
      ],
      "is_demo": true,
      "created_at": "2024-10-24T14:18:10Z"
    }
  ],
  "recommendations": [
    {
      "id": "2c3d4e5f-6a7b-8c9d-0e1f-2a3b4c5d6e7f",
      "investigation_id": "8a9b0c1d-2e3f-4a5b-6c7d-8e9f0a1b2c3d",
      "title": "Execute Runbook RB-402: Terminate Idle Transactions",
      "action_type": "immediate",
      "description": "Immediately relieves lock contention by terminating idle transactions older than 5 minutes.",
      "command_snippet": "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND query_start < NOW() - INTERVAL '5 min';",
      "risk_level": "LOW",
      "is_dry_run_safe": true,
      "requires_human_approval": true,
      "is_demo": true,
      "created_at": "2024-10-24T14:18:10Z"
    }
  ]
}
```

