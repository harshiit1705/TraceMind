# TraceMind Database Schema Design (Phase 2.3A)

## 1. Entity-Relationship Overview
The TraceMind data model supports multi-tenant distributed systems observability, incident management, automated root cause investigations, and remediation safety.

```mermaid
erDiagram
    ORGANIZATION ||--o{ PROJECT : owns
    PROJECT ||--o{ SERVICE : contains
    PROJECT ||--o{ INCIDENT : tracks
    SERVICE ||--o{ RUNBOOK : has
    INCIDENT ||--o{ INCIDENT_EVENT : logs
    INCIDENT ||--o| INVESTIGATION : triggers
    INCIDENT ||--o{ EVIDENCE : gathers
    INVESTIGATION ||--o{ FINDING : produces
    INVESTIGATION ||--o{ RECOMMENDATION : suggests
    INVESTIGATION ||--o{ INVESTIGATION_FEEDBACK : receives

    ORGANIZATION {
        uuid id PK
        string name
        string slug UK
        boolean is_demo
        datetime created_at
        datetime updated_at
    }

    PROJECT {
        uuid id PK
        uuid organization_id FK
        string name
        string slug
        string environment
        text description
        boolean is_demo
        datetime created_at
        datetime updated_at
    }

    SERVICE {
        uuid id PK
        uuid project_id FK
        string name
        string slug
        string identifier UK
        int tier
        string owner_team
        string status
        float request_rate_rps
        float error_rate_percent
        float p95_latency_ms
        jsonb metadata_json
        boolean is_demo
        datetime created_at
        datetime updated_at
    }

    INCIDENT {
        uuid id PK
        uuid project_id FK
        string incident_number UK
        string title
        string severity
        string status
        datetime started_at
        datetime mitigated_at
        datetime resolved_at
        string commander_name
        string commander_role
        string root_cause_summary
        jsonb affected_services
        text summary
        boolean is_demo
        datetime created_at
        datetime updated_at
    }

    INCIDENT_EVENT {
        uuid id PK
        uuid incident_id FK
        datetime timestamp
        string title
        string event_type
        string source
        text description
        jsonb payload
        datetime created_at
        datetime updated_at
    }

    INVESTIGATION {
        uuid id PK
        uuid incident_id FK
        string agent_name
        string status
        text summary
        int correlation_scope
        int spans_analyzed
        float confidence_score
        boolean is_demo
        datetime started_at
        datetime completed_at
        datetime created_at
        datetime updated_at
    }

    EVIDENCE {
        uuid id PK
        uuid incident_id FK
        string evidence_type
        string service_identifier
        string title
        text observation
        float confidence_weight
        datetime timestamp
        jsonb payload
        boolean is_demo
        datetime created_at
        datetime updated_at
    }

    FINDING {
        uuid id PK
        uuid investigation_id FK
        int rank
        string title
        text probable_root_cause
        text explanation
        string status
        float confidence_score
        jsonb affected_services
        jsonb supporting_evidence_ids
        boolean is_demo
        datetime created_at
        datetime updated_at
    }

    RECOMMENDATION {
        uuid id PK
        uuid investigation_id FK
        uuid finding_id FK
        string title
        string action_type
        text description
        text command_snippet
        string risk_level
        boolean is_dry_run_safe
        boolean requires_human_approval
        boolean is_demo
        datetime created_at
        datetime updated_at
    }

    RUNBOOK {
        uuid id PK
        uuid service_id FK
        string runbook_code UK
        string title
        text description
        string trigger_event
        jsonb steps
        boolean requires_approval
        boolean is_automated
        datetime created_at
        datetime updated_at
    }

    INVESTIGATION_FEEDBACK {
        uuid id PK
        uuid investigation_id FK
        string user_id
        int rating
        text comments
        boolean was_root_cause_accurate
        datetime created_at
        datetime updated_at
    }
```

---

## 2. Cross-Database Portability Strategy
To enable hermetic zero-network unit testing alongside high-performance PostgreSQL production deployments, TraceMind implements database abstraction types in `app/models/base.py`:

- **`GUID` Type Decorator**:
  - In PostgreSQL: Uses native binary `UUID(as_uuid=True)`.
  - In SQLite: Stores as `CHAR(36)` with automatic `uuid.UUID` coercion.
- **`JSONBCompat` Type Decorator**:
  - In PostgreSQL: Uses native binary `JSONB` for deep querying and indexing.
  - In SQLite: Stores as standard serializable `JSON` text.
- **UTC Timestamps**:
  - All timestamp fields enforce timezone awareness (`DateTime(timezone=True)`) defaulting to UTC `datetime.now(timezone.utc)`.

---

## 3. Indexing & Query Optimization
- Unique constraints on `(organization_id, slug)` for Projects and `(project_id, slug)` for Services.
- B-tree indexing on `incident_number` for sub-millisecond route lookup.
- Foreign key indexing on all parent relations (`project_id`, `incident_id`, `investigation_id`).
- Chronological indexing on `incident_events.timestamp` for efficient timeline rendering.

