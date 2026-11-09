from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


class Incident(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "incidents"

    project_id = Column(GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    incident_number = Column(String(32), unique=True, index=True, nullable=False)  # e.g., INC-8492
    correlation_group_id = Column(GUID, ForeignKey("correlation_groups.id", ondelete="SET NULL"), unique=True, index=True, nullable=True)
    title = Column(String(256), nullable=False)
    severity = Column(String(32), index=True, nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW
    status = Column(String(32), index=True, nullable=False)    # INVESTIGATING, ACKNOWLEDGED, MITIGATED, RESOLVED
    started_at = Column(DateTime(timezone=True), nullable=False)
    mitigated_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    commander_name = Column(String(128), default="Alex Chen", nullable=False)
    commander_role = Column(String(128), default="Staff SRE", nullable=False)
    root_cause_summary = Column(Text, nullable=True)
    affected_services = Column(JSONBCompat, default=list, nullable=False)
    summary = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=True, nullable=False)

    project = relationship("Project", back_populates="incidents")
    correlation_group = relationship("CorrelationGroup", back_populates="incidents")
    events = relationship("IncidentEvent", back_populates="incident", cascade="all, delete-orphan", order_by="IncidentEvent.timestamp.asc()")
    investigations = relationship("Investigation", back_populates="incident", cascade="all, delete-orphan")
    evidence_items = relationship("Evidence", back_populates="incident", cascade="all, delete-orphan")

