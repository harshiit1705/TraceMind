# TraceMind Backend Architecture (Phase 2.3A)

## 1. System Vision & Purpose
TraceMind is an AI-powered distributed systems observability and incident intelligence platform built to **"Understand failures. Find root causes. Restore reliability."**

The backend architecture provides a production-grade foundation built with **FastAPI**, **PostgreSQL**, **SQLAlchemy 2.x**, **Alembic**, and **Pydantic v2**, establishing strict domain boundaries, explicit data contracts, and deterministic simulation capabilities before introducing automated LLM reasoning and real-time streaming collectors in subsequent phases.

```mermaid
flowchart TD
    subgraph ClientLayer["Frontend Client & Consumers"]
        FE["TraceMind React SPA (Vite + TS)"]
        CLI["Admin CLI & Automated Agents"]
    end

    subgraph APILayer["FastAPI Application Layer (backend/app/api/v1)"]
        H["Health & Readiness Probes\n/health, /ready"]
        P["Project & Organization Catalog\n/projects, /projects/{id}/services"]
        S["Service Registry\n/services"]
        I["Incidents Command Center\n/incidents, /incidents/{id}, /timeline"]
        E["Telemetry Evidence Correlation\n/incidents/{id}/evidence"]
        INV["Autonomous Investigation Contracts\n/investigations/{id}"]
    end

    subgraph ServiceLayer["Domain Services & Business Logic (backend/app/services)"]
        PS["ProjectService"]
        IS["IncidentService"]
        EP["EvidenceProvider Protocol"]
        DEP["DemoEvidenceProvider (INC-8492)"]
    end

    subgraph RepositoryLayer["Data Access Layer (backend/app/repositories)"]
        PR["ProjectRepository"]
        SR["ServiceRepository"]
        IR["IncidentRepository"]
        INVR["InvestigationRepository"]
    end

    subgraph StorageLayer["Database & Persistence"]
        PG[("PostgreSQL 16 (Production / Local Docker)")]
        SQLITE[("In-Memory SQLite (Hermetic Unit Testing)")]
    end

    FE -->|HTTP / JSON (VITE_API_BASE_URL)| APILayer
    CLI -->|HTTP / JSON| APILayer

    H --> StorageLayer
    P --> PS
    S --> PS
    I --> IS
    E --> IS
    INV --> IS

    IS --> EP
    EP -.->|Implements| DEP

    PS --> PR
    PS --> SR
    IS --> IR
    IS --> INVR

    PR --> PG
    SR --> PG
    IR --> PG
    INVR --> PG
    PR -.->|Test Harness| SQLITE
    SR -.->|Test Harness| SQLITE
    IR -.->|Test Harness| SQLITE
    INVR -.->|Test Harness| SQLITE
```

---

## 2. Layered Architecture Principles
The TraceMind backend enforces a clean 4-tier layered architecture:

1. **API Router Layer (`app/api/v1/`)**:
   - Thin HTTP controllers responsible for route declaration, query parameter parsing, dependency injection, and HTTP status mapping.
   - Zero raw SQL or database session orchestration.
   - Validates incoming data against Pydantic request models and filters outgoing responses with strict response models.

2. **Domain Service Layer (`app/services/`)**:
   - Encapsulates high-level business rules, multi-repository coordination, seed data initialization, and telemetry correlation.
   - Uses abstract `EvidenceProvider` protocols, decoupling telemetry sourcing from the storage engine.

3. **Repository Layer (`app/repositories/`)**:
   - Provides clean abstractions over SQLAlchemy queries, joins, and filtering logic.
   - Enforces clean separation between query generation and business logic.

4. **Persistence & Database Models (`app/models/`, `app/db/`)**:
   - Portable SQLAlchemy declarative models utilizing UUID primary keys, JSONB metadata payloads, and UTC timestamps.
   - Compatible with PostgreSQL (production) and SQLite (hermetic local tests).

---

## 3. Incident INC-8492 Reference Architecture
In Phase 2.3A, the backend deterministically simulates the canonical incident **INC-8492**:
- **Root Cause**: Zombie idle transactions holding exclusive row locks on `orders_ledger_2024_q2` for >1,080 seconds.
- **Direct Impact**: Aurora PostgreSQL cluster connection pool exhausted at 980 / 1,000 max connections (98% saturation).
- **Failure Propagation**:
  1. `db:aurora-cluster-leader-az1`: 98% connection saturation, 14.2% error rate, 2,400ms P95 latency.
  2. `svc:stripe-ledger-adapter` (Payment Service): JDBC timeout spikes P99 latency to 1,420ms, error rate 8.85%.
  3. `svc:order-orchestration` (Order Service): Checkout transactions blocked, P99 latency 840ms, error rate 4.12%.
  4. `svc:ingress-proxy-v2` (API Gateway): Client timeouts (HTTP 504) reaching 2.84% error rate.
- **Safety Policy**: All recommended remediation commands (e.g. `pg_terminate_backend`) are strictly marked with `is_dry_run_safe = True` and `requires_human_approval = True`.

