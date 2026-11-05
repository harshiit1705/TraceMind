"""SQLAlchemy models for persistent anomaly detection baselines and events."""

from sqlalchemy import Column, String, Integer, Float, ForeignKey, DateTime, UniqueConstraint, Index, text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat, utc_now


class AnomalyBaseline(Base, UUIDMixin, TimestampMixin):
    """Persistent learned baseline state for a project/service/metric tuple."""
    __tablename__ = "anomaly_baselines"

    project_id = Column(GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    service_id = Column(GUID, ForeignKey("services.id", ondelete="CASCADE"), index=True, nullable=False)
    metric_name = Column(String(64), index=True, nullable=False)
    detection_method = Column(String(32), nullable=False)
    config_snapshot = Column(JSONBCompat, default=dict, nullable=False)
    baseline_state = Column(JSONBCompat, default=dict, nullable=False)
    sample_count = Column(Integer, default=0, nullable=False)
    last_event_timestamp = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, default=1, nullable=False)

    project = relationship("Project", back_populates="anomaly_baselines")
    service = relationship("Service", back_populates="anomaly_baselines")

    __table_args__ = (
        UniqueConstraint("project_id", "service_id", "metric_name", name="uq_project_service_metric_baseline"),
        Index("ix_anomaly_baselines_lookup", "project_id", "service_id", "metric_name"),
    )


class AnomalyEvent(Base, UUIDMixin, TimestampMixin):
    """Durable record of confirmed anomaly occurrences."""
    __tablename__ = "anomaly_events"

    project_id = Column(GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    service_id = Column(GUID, ForeignKey("services.id", ondelete="CASCADE"), index=True, nullable=False)
    metric_name = Column(String(64), index=True, nullable=False)
    observed_value = Column(Float, nullable=False)
    expected_baseline = Column(Float, nullable=True)
    deviation_pct = Column(Float, nullable=True)
    severity = Column(String(32), nullable=False)
    detection_method = Column(String(32), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    detected_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    status = Column(String(32), default="OPEN", nullable=False)
    source_event_id = Column(String(128), nullable=True, index=True)
    explanation = Column(String(512), nullable=True)

    project = relationship("Project", back_populates="anomaly_events")
    service = relationship("Service", back_populates="anomaly_events")

    __table_args__ = (
        Index("ix_anomaly_events_service_metric_occurred", "project_id", "service_id", "metric_name", "occurred_at"),
        Index(
            "uq_anomaly_events_source_event_id",
            "project_id",
            "service_id",
            "metric_name",
            "source_event_id",
            unique=True,
            postgresql_where=text("source_event_id IS NOT NULL"),
            sqlite_where=text("source_event_id IS NOT NULL"),
        ),
    )

