# TraceMind Backend Developer Setup Guide

This guide covers running and testing the TraceMind backend service locally and with Docker.

---

## 1. Prerequisites
- **Python**: 3.11+ (Python 3.11, 3.12, or 3.13)
- **Node.js**: 20+ (for frontend)
- **Docker & Docker Compose**: (optional, for running local PostgreSQL)

---

## 2. Local Environment Setup

### A. Create and Activate Virtual Environment
```bash
# From workspace root
cd backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On macOS / Linux:
source .venv/bin/activate
```

### B. Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### C. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Default local configuration:
```env
APP_NAME="TraceMind API"
APP_VERSION="0.2.3a"
ENVIRONMENT="development"
DEBUG=true
API_V1_PREFIX="/api/v1"
DATABASE_URL="postgresql+psycopg2://tracemind:tracemind_secret@localhost:5432/tracemind_db"
DEMO_MODE=true
CORS_ORIGINS='["http://localhost:5173", "http://127.0.0.1:5173"]'
```

---

## 3. Database Setup & Migrations

### Option A: Run PostgreSQL via Docker Compose
Start PostgreSQL 16:
```bash
docker compose up -d db
```

### Option B: Run Alembic Migrations
Apply database schema migrations:
```bash
cd backend
alembic upgrade head
```

Roll back migrations:
```bash
alembic downgrade -1
```

---

## 4. Running the Backend Server
Start the local development server with hot-reload:
```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Once started, access:
- **API Root**: `http://localhost:8000/`
- **Interactive OpenAPI Docs**: `http://localhost:8000/docs`
- **Health Probe**: `http://localhost:8000/api/v1/health`
- **Readiness Probe**: `http://localhost:8000/api/v1/ready`

---

## 5. Running the Hermetic Automated Test Suite
The test suite runs against an isolated, in-memory SQLite database and requires zero external network or database connections.

```bash
# From workspace root
$env:PYTHONPATH="backend"; $env:ENVIRONMENT="test"; $env:DATABASE_URL="sqlite:///:memory:"
pytest backend/tests -v
```

Expected output:
```text
======================== 20 passed, 1 warning in 3.24s ========================
```

---

## 6. Full-Stack Docker Compose Deployment
To run both the PostgreSQL database and the TraceMind FastAPI backend together:
```bash
docker compose up --build
```
This builds the container image defined in `backend/Dockerfile` and connects to the healthy PostgreSQL container.

