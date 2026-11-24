# TraceMind

**Understand failures. Find root causes. Restore reliability.**

TraceMind is a distributed-systems observability and incident-intelligence demo. It collects application metrics, structured logs, and distributed spans; evaluates statistical anomalies; correlates related anomaly events; ranks probable root causes; and supports evidence-grounded investigation and human-approved recovery workflows.

This repository contains the frontend, FastAPI backend, and three local demo microservices. It is intended for local development and recruiter demonstrations, not as a production-ready hosted service.

## What is implemented

| Area | Included capability |
|---|---|
| Service observability | Metrics, structured logs, distributed trace spans, service registry, dependency graph |
| Anomaly detection | Service-scoped rolling/EWMA baselines, warm-up screening, event-time ordering, persisted anomaly events |
| Correlation | Project-scoped temporal/topological clustering, root-cause ranking, idempotent correlation groups, incident synchronization |
| Multi-signal RCA | Evidence assembled from anomalies, metrics, logs, traces, and service topology |
| AI investigation | Gemini-backed structured investigation with evidence validation and persisted results |
| Incident management | Incident queue, lifecycle transitions, timelines, and linked correlation groups |
| Recovery workflow | Human approval, allowlisted actions, execution audit, and recovery verification |
| Demo environment | Order, Payment, and Inventory services with controlled fault injection |

### Important scope boundaries

- Correlation is **manually triggered** from the Services page. There is no background correlation scheduler.
- The default correlation evaluation window is **five minutes**, and a group normally requires at least two related anomaly events. Generate fresh telemetry and evaluate promptly.
- Logs and traces are separate signals; their presence alone does not prove that an `AnomalyEvent` was created.
- Live Gemini investigation requires a valid `GEMINI_API_KEY`. Without it, the core observability and incident workflow can still be demonstrated, but live AI synthesis is unavailable.
- In the local demo fleet, **`RESET_SERVICE_FAULTS`** is the only natively real remediation action. Other allowlisted infrastructure actions are explicitly simulated.
- Settings and Reports are frontend scaffolds and are not backed by corresponding live backend APIs in this package. Do not present their static values as live configuration or live reliability KPIs.
- Seeded incidents and sample dashboard values are demo data. Distinguish them from incidents created during a live telemetry run.

## Architecture

```text
React + TypeScript + Vite
          |
          | HTTP / JSON
          v
FastAPI backend (:8000)
  |        |         |
  |        |         +--> Gemini investigation (optional)
  |        |
  |        +--> SQLAlchemy / Alembic
  |                    |
  |                    v
  |                PostgreSQL
  |
  +--> Metrics / Logs / Traces ingestion
  +--> Anomaly detection
  +--> Correlation + RCA
  +--> Incidents / Remediation / Verification

Demo microservices
  Order (:8001) --> Inventory (:8003)
        |
        +--------> Payment (:8002)
        |
        +--------> TraceMind telemetry collector
```

**Main stack:** React 18, TypeScript, Vite, Tailwind CSS, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Pytest, and Google GenAI SDK.

## Requirements

- Python 3.11+
- Node.js 22.6+ and npm
- Docker Desktop / Docker Compose for the included PostgreSQL service
- Optional: Gemini API key for live AI investigation

## Windows setup

Run these commands from the repository root.

### 1. Start PostgreSQL

```powershell
docker compose up -d db
```

The default local database is:
- Database: `tracemind_db`
- User: `tracemind`
- Port: `5432`

For another database, edit `backend/.env` before starting the application.

### 2. Configure the backend

```powershell
Copy-Item backend\.env.example backend\.env
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Edit `backend\.env` if needed. Add `GEMINI_API_KEY` only if you want live Gemini investigation. Never commit a real key.

### 3. Configure and install the frontend

```powershell
Copy-Item frontend\.env.example frontend\.env
cd frontend
npm ci
cd ..
```

The frontend example configuration uses API mode and points to `http://localhost:8000`.

### 4. Start the full demo

```powershell
scripts\start_demo.bat
```

The launcher:
1. Checks required ports and local frontend dependencies.
2. Applies `alembic upgrade head` to the configured backend database.
3. Starts the backend, demo microservices, and Vite frontend.
4. Checks backend database readiness and each service health endpoint.
5. Stops child processes when you press `Ctrl+C`.

Open **http://localhost:5173**.

If the launcher reports a port conflict, stop the process already using that port before retrying. If migration fails, verify that PostgreSQL is running and `backend/.env` contains the correct `DATABASE_URL`.

### Useful local URLs

| Component | URL |
|---|---|
| TraceMind frontend | http://localhost:5173 |
| Backend health | http://localhost:8000/api/v1/health |
| Backend readiness (includes database check) | http://localhost:8000/api/v1/ready |
| Backend OpenAPI docs | http://localhost:8000/docs |
| Order Service docs | http://localhost:8001/docs |
| Payment Service docs | http://localhost:8002/docs |
| Inventory Service docs | http://localhost:8003/docs |

## Recruiter demonstration flow

The recruiter-facing walkthrough should stay in the TraceMind frontend. Swagger is useful beforehand to prepare the demo fault; it is not the main product walkthrough.

1. **Prepare a healthy baseline.** Ensure the Payment Service fault configuration is `none`. If using a fresh database, send at least three successful payment requests in separate telemetry aggregation windows so the detector can warm up.
2. **Inject a controlled failure.** In Payment Service Swagger, use `POST /faults` with `fault_type: "error_rate"`, `error_rate_pct: 100`, and `error_status_code: 502`.
3. **Generate traffic.** Submit several `POST /payments/charge` requests and confirm they fail with HTTP 502.
4. **Allow telemetry to flush.** Wait a few seconds for the asynchronous collector to send metrics, logs, and spans.
5. **Verify signals in TraceMind.** Inspect Logs and Traces. Then confirm that fresh anomaly events were persisted; logs alone are not enough for correlation.
6. **Trigger correlation in the frontend.** Open Services, select Payment Service, and click **Correlate Incidents**. Keep the evaluation within the five-minute window.
7. **Inspect the result.** A successful correlation returns one or more groups and synchronizes them with the incident lifecycle. A zero-group result is now shown as a warning and does not navigate away or claim an incident was created.
8. **Investigate and recover.** Open the resulting incident, review its telemetry evidence and probable root-cause ranking, run the Gemini investigation if configured, and demonstrate an approved remediation. For the real demo reset action, verify the Payment Service returns to healthy state.

**Reset the fault after the demonstration** using `POST /faults/reset` and confirm `GET /health` returns healthy.

## Tests and verification

### Backend tests

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "backend"
$env:ENVIRONMENT = "test"
$env:DATABASE_URL = "sqlite:///:memory:"
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

The PostgreSQL-specific integration tests require a separately configured PostgreSQL test database. The Gemini provider tests require the installed Google GenAI SDK; tests that exercise live provider access should use mocks or a dedicated test key, never a personal production key.

### Demo microservice tests

```powershell
$env:PYTHONPATH = "demo-microservices;backend"
$env:ENVIRONMENT = "test"
$env:DATABASE_URL = "sqlite:///:memory:"
backend\.venv\Scripts\python.exe -m pytest demo-microservices\tests -q
```

### Frontend tests and build

```powershell
cd frontend
npm test
npm run typecheck
npm run build
```

The frontend test script uses Node's built-in TypeScript type stripping, hence the Node.js 22.6+ requirement.

## Repository layout

```text
backend/             FastAPI app, domain services, repositories, migrations, tests
frontend/            React application and feature pages
demo-microservices/  Order, Payment, Inventory services and telemetry client
design/              Existing UI design references
docs/                Architecture and setup notes
scripts/             Local launchers and optional demo helpers
```

## Engineering principles

- Preserve project boundaries and explicit API contracts.
- Keep anomaly detection and correlation deterministic and explainable.
- Treat AI output as an interpretation of persisted evidence, not as evidence itself.
- Require human approval for remediation.
- Distinguish real execution from simulated execution.
- Prefer small, verifiable changes over adding features that are not needed for the demonstration.
