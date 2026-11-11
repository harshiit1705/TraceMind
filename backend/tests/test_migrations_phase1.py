"""Alembic migration lifecycle verification for Sprint 6 Phase 1 (0006, 0007, 0008)."""

import os
import shutil
import sqlite3
import tempfile
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.db.session import Base
import app.models  # noqa: F401


def test_phase1_migrations_upgrade_downgrade_cycle(monkeypatch):
    """Verify migrations 0006 -> 0007 -> 0008 upgrade, downgrade to 0005, and re-upgrade on SQLite."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_phase1_mig.db").replace("\\", "/")
    db_url = f"sqlite:///{db_path}"

    from app.core.config import settings
    monkeypatch.setattr(settings, "DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL", db_url)

    try:
        # 1. Create schema up to 0005 by creating all tables and dropping the 3 new Phase 1 tables
        engine = create_engine(db_url)
        Base.metadata.create_all(bind=engine)
        engine.dispose()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS trace_spans")
        cur.execute("DROP TABLE IF EXISTS application_logs")
        cur.execute("DROP TABLE IF EXISTS metric_samples")
        conn.commit()
        conn.close()

        cfg = Config("backend/alembic.ini")
        command.stamp(cfg, "0005_incident_correlation_link")

        # 2. Upgrade 0005 -> 0008 (head)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert "metric_samples" in tables
        assert "application_logs" in tables
        assert "trace_spans" in tables
        conn.close()

        # 3. Downgrade 0008 -> 0005
        command.downgrade(cfg, "0005_incident_correlation_link")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables_after_down = {row[0] for row in cur.fetchall()}
        assert "metric_samples" not in tables_after_down
        assert "application_logs" not in tables_after_down
        assert "trace_spans" not in tables_after_down
        conn.close()

        # 4. Re-upgrade 0005 -> 0008
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables_reup = {row[0] for row in cur.fetchall()}
        assert "metric_samples" in tables_reup
        assert "application_logs" in tables_reup
        assert "trace_spans" in tables_reup
        conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
