# TraceMind local setup

The canonical setup and recruiter demonstration instructions are maintained in the repository root [`README.md`](../README.md).

This note is retained as a short pointer so older links do not lead to outdated setup commands.

## Quick checklist

1. Install Python 3.11+, Node.js 22.6+, npm, and Docker Desktop.
2. Start the PostgreSQL service with `docker compose up -d db`.
3. Copy `backend/.env.example` to `backend/.env` and configure `DATABASE_URL`.
4. Create `backend/.venv` and install `backend/requirements.txt`.
5. Copy `frontend/.env.example` to `frontend/.env` and run `npm ci` in `frontend/`.
6. Start the full local environment with `scripts/start_demo.bat`.

The launcher applies Alembic migrations before starting the backend and checks database readiness plus all local service health endpoints.

## Tests

See the root README for the current backend, demo-microservice, and frontend test commands. PostgreSQL integration tests and live Gemini provider calls require their corresponding external services/configuration.
