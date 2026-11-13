"""Alembic migration lifecycle verification for TraceMind (0001 -> 0009 head)."""

import os
import shutil
import sqlite3
import tempfile
from uuid import uuid4
from datetime import datetime, timezone
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
import app.models  # noqa: F401
from app.services.project_service import ProjectService


def test_fresh_sqlite_migration_0001_to_head_and_model_consistency(monkeypatch):
    """Verify fresh SQLite DB upgrades 0001 -> 0008, preserves data across 0004 batch alter,
    downgrades cleanly to base, re-upgrades to head, and matches all SQLAlchemy models."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_fresh_mig.db").replace("\\", "/")
    db_url = f"sqlite:///{db_path}"

    from app.core.config import settings
    monkeypatch.setattr(settings, "DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL", db_url)

    try:
        cfg = Config("backend/alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        assert len(script.get_heads()) == 1
        current_head = script.get_heads()[0]
        assert current_head == "0011_remediation_hardening_and_recovery_verification"

        # 1. Upgrade fresh DB up to 0003 and seed pre-0004 data
        command.upgrade(cfg, "0003_service_dependencies_and_correlation")

        org_id = str(uuid4())
        proj_id = str(uuid4())
        inc_id = str(uuid4())
        inv_id = str(uuid4())
        now_str = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO organizations (id, slug, name, tier, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (org_id, "test-org", "Test Org", "enterprise", "{}", now_str, now_str),
        )
        cur.execute(
            "INSERT INTO projects (id, organization_id, slug, name, environment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (proj_id, org_id, "test-proj", "Test Project", "production", now_str, now_str),
        )
        cur.execute(
            "INSERT INTO incidents (id, project_id, incident_number, title, severity, status, started_at, commander_name, commander_role, affected_services, is_demo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (inc_id, proj_id, "INC-001", "Legacy Outage", "HIGH", "INVESTIGATING", now_str, "Alex", "SRE", "[]", 0, now_str, now_str),
        )
        cur.execute(
            "INSERT INTO investigations (id, incident_id, agent_name, status, correlation_scope, spans_analyzed, is_demo, started_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (inv_id, inc_id, "Agent #1", "COMPLETED", 2, 10, 0, now_str, now_str, now_str),
        )
        conn.commit()
        conn.close()

        # 2. Upgrade 0003 -> 0008 (including batch-mode 0004 & 0005 & Phase 1 0006-0008)
        command.upgrade(cfg, "head")

        # 3. Verify pre-0004 investigation & incident data survived batch rebuild intact
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, incident_id, agent_name, provider, model_name FROM investigations WHERE id = ?", (inv_id,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == inv_id
        assert row[1] == inc_id
        assert row[2] == "Agent #1"
        assert row[3] == "google-gemini"

        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] == current_head
        conn.close()

        # 4. Verify every SQLAlchemy model table and column matches migrated schema + ORM works
        engine = create_engine(db_url)
        insp = inspect(engine)
        migrated_tables = set(insp.get_table_names())
        for table_name, table in Base.metadata.tables.items():
            assert table_name in migrated_tables, f"Missing table {table_name} after 0001->head migration"
            migrated_cols = {c["name"] for c in insp.get_columns(table_name)}
            model_cols = {c.name for c in table.columns}
            missing = model_cols - migrated_cols
            assert not missing, f"Table {table_name} missing columns {missing}"

        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            proj = ProjectService(db).ensure_default_seed()
            assert proj.slug == "core-ecommerce"
        finally:
            db.close()
            engine.dispose()

        # 5. Full downgrade head -> base -> re-upgrade head
        command.downgrade(cfg, "base")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'")
        assert cur.fetchall() == []
        conn.close()

        command.upgrade(cfg, "head")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] == current_head
        conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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

        # 2. Upgrade 0005 -> 0008
        command.upgrade(cfg, "0008_distributed_trace_spans_table")

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
        command.upgrade(cfg, "0008_distributed_trace_spans_table")

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
