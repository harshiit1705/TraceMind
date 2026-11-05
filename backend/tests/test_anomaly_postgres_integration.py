"""Dedicated PostgreSQL Integration Test Suite for Anomaly Persistence & Concurrency.

These integration tests execute against a real PostgreSQL instance using independent
database sessions and transactions. They verify PostgreSQL-specific features such as
transaction-level advisory locks (`pg_advisory_xact_lock`), `SELECT ... FOR UPDATE`
row-level locking, and PostgreSQL partial unique indexes.

When PostgreSQL is unavailable (e.g. Docker daemon not running), these tests are
gracefully skipped with an informative diagnostic message rather than failing.
"""

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.models.anomaly import AnomalyBaseline, AnomalyEvent
from app.models.organization import Organization
from app.models.project import Project
from app.models.service import Service
from app.schemas.anomaly import AnomalyEvaluationRequest
from app.services.anomaly.registry import get_anomaly_registry
from app.services.anomaly.service import AnomalyService

# Target PostgreSQL connection URL from environment or default docker-compose setup
PG_URL = os.getenv(
    "POSTGRES_TEST_DATABASE_URL",
    "postgresql+psycopg2://tracemind:tracemind_secret@localhost:5432/tracemind_db",
)


def check_postgres_connection() -> bool:
    """Check whether a real PostgreSQL database is reachable."""
    try:
        test_engine = create_engine(PG_URL, connect_args={"connect_timeout": 2}, pool_pre_ping=True)
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        test_engine.dispose()
        return True
    except Exception:
        return False


POSTGRES_AVAILABLE = check_postgres_connection()
pytestmark = pytest.mark.skipif(
    not POSTGRES_AVAILABLE,
    reason=(
        f"PostgreSQL database unavailable at {PG_URL}. "
        "Live PostgreSQL integration tests skipped. "
        "To run, execute: 'docker compose up -d db' and re-run pytest."
    ),
)


@pytest.fixture(scope="module")
def pg_engine():
    """Create a persistent engine connected to the PostgreSQL database."""
    if not POSTGRES_AVAILABLE:
        yield None
        return

    engine = create_engine(PG_URL, pool_size=10, max_overflow=5)
    # Ensure tables exist for testing
    from app.models import Base
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_session(pg_engine) -> Generator[Session, None, None]:
    """Provide an isolated session with seeded test tenant on PostgreSQL."""
    SessionFactory = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
    session = SessionFactory()

    # Ensure test project and service exist
    org = session.query(Organization).filter_by(slug="test-pg-org").first()
    if not org:
        org = Organization(slug="test-pg-org", name="PG Integration Test Org")
        session.add(org)
        session.flush()

    project = session.query(Project).filter_by(slug="test-pg-proj").first()
    if not project:
        project = Project(
            organization_id=org.id,
            slug="test-pg-proj",
            name="PG Integration Test Project",
        )
        session.add(project)
        session.flush()

    service = session.query(Service).filter_by(slug="test-pg-svc").first()
    if not service:
        service = Service(
            project_id=project.id,
            slug="test-pg-svc",
            name="PG Test Service",
            identifier="svc:pg-test-service",
            tier=1,
            owner_team="Platform",
            status="healthy",
        )
        session.add(service)
        session.flush()

    session.commit()
    get_anomaly_registry().reset_all()

    try:
        yield session
    finally:
        session.close()
        get_anomaly_registry().reset_all()


def test_pg_concurrent_first_time_baseline_creation(pg_engine, pg_session: Session):
    """Verify PostgreSQL advisory lock synchronizes concurrent first-time baseline creation.

    Multiple worker threads simultaneously send the first measurement for a brand new metric.
    Advisory lock `pg_advisory_xact_lock` prevents race conditions or unique constraint errors.
    """
    proj = pg_session.query(Project).filter_by(slug="test-pg-proj").first()
    svc = pg_session.query(Service).filter_by(slug="test-pg-svc").first()

    unique_metric = f"first_time_{uuid4().hex[:8]}"
    SessionFactory = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)

    errors = []
    base_time = datetime.now(timezone.utc)

    def worker(worker_id: int):
        session = SessionFactory()
        try:
            anomaly_svc = AnomalyService(session)
            req = AnomalyEvaluationRequest(
                project_id=proj.id,
                service_identifier=svc.identifier,
                metric_name=unique_metric,
                observed_value=100.0,
                timestamp=base_time + timedelta(seconds=worker_id + 1),
            )
            res = anomaly_svc.evaluate_measurement(req)
            assert res is not None
        except Exception as e:
            errors.append(e)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Must complete with zero concurrency or duplicate key errors
    assert len(errors) == 0

    # Exactly one baseline row must exist for this metric
    baselines = (
        pg_session.query(AnomalyBaseline)
        .filter(
            AnomalyBaseline.project_id == proj.id,
            AnomalyBaseline.service_id == svc.id,
            AnomalyBaseline.metric_name == unique_metric,
        )
        .all()
    )
    assert len(baselines) == 1
    assert baselines[0].version >= 1


def test_pg_concurrent_duplicate_anomaly_submissions(pg_engine, pg_session: Session):
    """Verify partial unique index on PostgreSQL prevents duplicate anomaly event rows."""
    proj = pg_session.query(Project).filter_by(slug="test-pg-proj").first()
    svc = pg_session.query(Service).filter_by(slug="test-pg-svc").first()

    metric = f"dup_anomaly_{uuid4().hex[:8]}"
    source_event_id = f"evt-pg-{uuid4().hex[:8]}"
    t0 = datetime.now(timezone.utc)

    # 1. Warm up baseline with 4 samples
    anomaly_svc = AnomalyService(pg_session)
    for i in range(4):
        anomaly_svc.evaluate_measurement(
            AnomalyEvaluationRequest(
                project_id=proj.id,
                service_identifier=svc.identifier,
                metric_name=metric,
                observed_value=100.0,
                timestamp=t0 + timedelta(seconds=i * 5),
            )
        )

    # 2. Concurrently submit identical anomaly measurement with same source_event_id
    SessionFactory = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
    errors = []
    results = []
    spike_time = t0 + timedelta(seconds=60)

    def worker():
        session = SessionFactory()
        try:
            svc_instance = AnomalyService(session)
            req = AnomalyEvaluationRequest(
                project_id=proj.id,
                service_identifier=svc.identifier,
                metric_name=metric,
                observed_value=400.0,
                timestamp=spike_time,
                source_event_id=source_event_id,
            )
            res = svc_instance.evaluate_measurement(req)
            results.append(res)
        except Exception as e:
            errors.append(e)
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(results) == 3
    for r in results:
        assert r.is_anomaly is True
        assert r.observed_value == 400.0

    # Verify only ONE anomaly event record was persisted in PostgreSQL
    events = (
        pg_session.query(AnomalyEvent)
        .filter(
            AnomalyEvent.project_id == proj.id,
            AnomalyEvent.service_id == svc.id,
            AnomalyEvent.source_event_id == source_event_id,
        )
        .all()
    )
    assert len(events) == 1


def test_pg_atomic_persistence_of_anomaly_events_and_watermark(pg_session: Session):
    """Verify anomaly event and watermark timestamp are atomically committed in PostgreSQL."""
    proj = pg_session.query(Project).filter_by(slug="test-pg-proj").first()
    svc = pg_session.query(Service).filter_by(slug="test-pg-svc").first()

    metric = f"atomic_spike_{uuid4().hex[:8]}"
    t0 = datetime.now(timezone.utc)
    anomaly_svc = AnomalyService(pg_session)

    # Warm up baseline
    for i in range(4):
        anomaly_svc.evaluate_measurement(
            AnomalyEvaluationRequest(
                project_id=proj.id,
                service_identifier=svc.identifier,
                metric_name=metric,
                observed_value=50.0,
                timestamp=t0 + timedelta(seconds=i * 5),
            )
        )

    baseline_before = (
        pg_session.query(AnomalyBaseline)
        .filter(AnomalyBaseline.project_id == proj.id, AnomalyBaseline.metric_name == metric)
        .first()
    )
    v_before = baseline_before.version
    samples_before = list(baseline_before.baseline_state["baseline"]["samples"])

    # Trigger anomaly
    spike_time = t0 + timedelta(seconds=50)
    res = anomaly_svc.evaluate_measurement(
        AnomalyEvaluationRequest(
            project_id=proj.id,
            service_identifier=svc.identifier,
            metric_name=metric,
            observed_value=250.0,
            timestamp=spike_time,
        )
    )
    assert res.is_anomaly is True

    # Verify in PostgreSQL
    pg_session.expire_all()
    baseline_after = (
        pg_session.query(AnomalyBaseline)
        .filter(AnomalyBaseline.project_id == proj.id, AnomalyBaseline.metric_name == metric)
        .first()
    )
    # Watermark advanced and version incremented
    assert baseline_after.version == v_before + 1
    assert baseline_after.last_event_timestamp == spike_time
    # Anti-contamination: sample list unchanged
    assert baseline_after.baseline_state["baseline"]["samples"] == samples_before

    event = (
        pg_session.query(AnomalyEvent)
        .filter(AnomalyEvent.project_id == proj.id, AnomalyEvent.metric_name == metric)
        .first()
    )
    assert event is not None
    assert event.observed_value == 250.0
    assert event.occurred_at == spike_time

