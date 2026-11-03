import os
from typing import Generator
import pytest

# Ensure test environment settings are set before any app modules are loaded
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DEMO_MODE"] = "true"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
get_settings.cache_clear()

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.project_service import ProjectService
from app.services.incident_service import IncidentService

# In-memory hermetic SQLite engine for automated unit tests
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def seed_test_database():
    """Create fresh schema and seed deterministic data before each test."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    session = TestingSessionLocal()
    try:
        proj_svc = ProjectService(session)
        proj_svc.ensure_default_seed()
        inc_svc = IncidentService(session)
        inc_svc.ensure_default_seed()
    finally:
        session.close()

    yield


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """Provide an isolated database session per test."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient with get_db dependency overridden to the test session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
