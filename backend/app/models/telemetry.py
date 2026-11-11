"""SQLAlchemy models for persistent application metrics, structured logs, and distributed trace spans."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.models.base import GUID, JSONBCompat, TimestampMixin, UUIDMixin


class MetricSample(Base, UUIDMixin, TimestampMixin):
    """Persistent raw application telemetry metric sample."""

    __tablename__ = "metric_samples"

    project_id = Column(
        GUID,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    service_id = Column(
        GUID,
        ForeignKey("services.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    metric_name = Column(String(64), nullable=False)
    metric_unit = Column(String(32), default="", nullable=False)
    value = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    endpoint = Column(String(256), nullable=True)
    http_status_code = Column(Integer, nullable=True)
    request_id = Column(String(128), nullable=True, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    source_event_id = Column(String(128), nullable=True)
    attributes_json = Column(JSONBCompat, default=dict, nullable=False)

    project = relationship("Project")
    service = relationship("Service")

    __table_args__ = (
        Index(
            "ix_metric_samples_lookup",
            "project_id",
            "service_id",
            "metric_name",
            "timestamp",
        ),
        Index(
            "ix_metric_samples_project_time",
            "project_id",
            "timestamp",
        ),
        Index(
            "uq_metric_samples_source_event_id",
            "project_id",
            "service_id",
            "metric_name",
            "source_event_id",
            unique=True,
            postgresql_where=text("source_event_id IS NOT NULL"),
            sqlite_where=text("source_event_id IS NOT NULL"),
        ),
    )


class ApplicationLog(Base, UUIDMixin, TimestampMixin):
    """Persistent structured application log record."""

    __tablename__ = "application_logs"

    project_id = Column(
        GUID,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    service_id = Column(
        GUID,
        ForeignKey("services.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    level = Column(String(16), nullable=False)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    message = Column(Text, nullable=False)
    request_id = Column(String(128), nullable=True, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    span_id = Column(String(32), nullable=True, index=True)
    source_event_id = Column(String(128), nullable=True)
    attributes_json = Column(JSONBCompat, default=dict, nullable=False)
    exception_type = Column(String(128), nullable=True)
    exception_message = Column(Text, nullable=True)

    project = relationship("Project")
    service = relationship("Service")

    __table_args__ = (
        Index(
            "ix_application_logs_query",
            "project_id",
            "service_id",
            "level",
            "timestamp",
        ),
        Index(
            "ix_application_logs_trace",
            "project_id",
            "trace_id",
            "timestamp",
        ),
        Index(
            "uq_application_logs_source_event_id",
            "project_id",
            "service_id",
            "source_event_id",
            unique=True,
            postgresql_where=text("source_event_id IS NOT NULL"),
            sqlite_where=text("source_event_id IS NOT NULL"),
        ),
    )


class TraceSpan(Base, UUIDMixin, TimestampMixin):
    """Persistent distributed trace span representing one instrumented operation."""

    __tablename__ = "trace_spans"

    project_id = Column(
        GUID,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    service_id = Column(
        GUID,
        ForeignKey("services.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    trace_id = Column(String(64), nullable=False, index=True)
    span_id = Column(String(32), nullable=False)
    parent_span_id = Column(String(32), nullable=True, index=True)
    operation_name = Column(String(256), nullable=False)
    span_kind = Column(String(16), default="server", nullable=False)  # server, client, internal, database
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=False)
    duration_ms = Column(Float, nullable=False)
    status = Column(String(16), default="ok", nullable=False)  # ok, error
    http_status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    request_id = Column(String(128), nullable=True, index=True)
    attributes_json = Column(JSONBCompat, default=dict, nullable=False)

    project = relationship("Project")
    service = relationship("Service")

    __table_args__ = (
        UniqueConstraint("project_id", "trace_id", "span_id", name="uq_project_trace_span"),
        Index(
            "ix_trace_spans_trace_lookup",
            "project_id",
            "trace_id",
            "start_time",
        ),
        Index(
            "ix_trace_spans_service_time",
            "project_id",
            "service_id",
            "start_time",
        ),
        Index(
            "ix_trace_spans_root_list",
            "project_id",
            "parent_span_id",
            "start_time",
        ),
    )

