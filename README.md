# TraceMind

**Understand failures. Find root causes. Restore reliability.**

TraceMind is an AI-powered distributed systems observability and incident intelligence platform designed to detect abnormal system behaviour, preserve historical baselines, and help engineers investigate potential root causes of production incidents.

## Current Capabilities

- **Anomaly Detection:** Detect abnormal application measurements using rolling-average and EWMA-based detection.
- **Historical Baselines:** Persist detector state and restore it after backend restarts.
- **Anomaly Persistence:** Store confirmed anomaly events and maintain event-time watermarks.
- **Persistence Safety:** Implement transaction-aware persistence, timestamp validation, and PostgreSQL concurrency safeguards.

## Architecture

### Backend
- Python
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- PostgreSQL
- Alembic
- Pytest

### Frontend
- React
- TypeScript
- Vite

## Project Structure

```text
TraceMind/
├── backend/
│   ├── app/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── ...
│   ├── migrations/
│   └── tests/
├── frontend/
└── README.md
```

## Development Status

| Sprint | Capability | Status |
|---|---|---|
| Sprint 1 | Project foundation and service management | Implemented |
| Sprint 2 | Statistical anomaly detection | Implemented |
| Sprint 3 | PostgreSQL anomaly persistence | Implemented; live PostgreSQL verification pending |

The backend regression suite currently reports 55 passing tests. Three dedicated PostgreSQL integration tests remain unverified because a live PostgreSQL environment was unavailable during the latest test run.

## Roadmap

- Cross-service anomaly correlation
- Probable root-cause ranking
- Evidence-grounded AI investigation
- Incident intelligence
- Human-approved recovery recommendations

## Engineering Philosophy

TraceMind prioritizes deterministic detection, explainable evidence, reliable persistence, and human oversight.

AI should interpret supporting engineering evidence rather than invent it.

---

**Project status:** Active development.