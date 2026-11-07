from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Float, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


class Investigation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "investigations"

    incident_id = Column(GUID, ForeignKey("incidents.id", ondelete="SET NULL"), index=True, nullable=True)
    correlation_group_id = Column(GUID, ForeignKey("correlation_groups.id", ondelete="SET NULL"), index=True, nullable=True)
    provider = Column(String(64), server_default="google-gemini", default="google-gemini", nullable=False)
    model_name = Column(String(64), server_default="gemini-2.0-flash", default="gemini-2.0-flash", nullable=False)
    prompt_version = Column(String(32), server_default="v1.0", default="v1.0", nullable=False)
    schema_version = Column(String(32), server_default="v1.0", default="v1.0", nullable=False)
    status = Column(String(32), default="PENDING", index=True, nullable=False)  # PENDING, RUNNING, COMPLETED, FAILED
    agent_name = Column(String(128), default="Autonomous Agent #4", nullable=False)
    summary = Column(Text, nullable=True)
    investigation_json = Column(JSONBCompat, nullable=True)
    evidence_hash = Column(String(64), nullable=True, index=True)
    correlation_scope = Column(Integer, default=0, nullable=False)
    spans_analyzed = Column(Integer, default=0, nullable=False)
    confidence_score = Column(Float, nullable=True)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    latency_ms = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    incident = relationship("Incident", back_populates="investigations")
    correlation_group = relationship("CorrelationGroup", back_populates="investigations")
    evidence_items = relationship("Evidence", back_populates="investigation")
    findings = relationship("Finding", back_populates="investigation", cascade="all, delete-orphan", order_by="Finding.rank.asc()")
    recommendations = relationship("Recommendation", back_populates="investigation", cascade="all, delete-orphan")
    feedback = relationship("InvestigationFeedback", back_populates="investigation", cascade="all, delete-orphan")

