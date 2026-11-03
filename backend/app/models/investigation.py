from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Float, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID


class Investigation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "investigations"

    incident_id = Column(GUID, ForeignKey("incidents.id", ondelete="CASCADE"), index=True, nullable=False)
    agent_name = Column(String(128), default="Autonomous Agent #4", nullable=False)
    status = Column(String(32), default="COMPLETED", index=True, nullable=False)  # PENDING, RUNNING, COMPLETED, FAILED
    summary = Column(Text, nullable=True)
    correlation_scope = Column(Integer, default=0, nullable=False)
    spans_analyzed = Column(Integer, default=0, nullable=False)
    confidence_score = Column(Float, nullable=True)
    is_demo = Column(Boolean, default=True, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    incident = relationship("Incident", back_populates="investigations")
    evidence_items = relationship("Evidence", back_populates="investigation")
    findings = relationship("Finding", back_populates="investigation", cascade="all, delete-orphan", order_by="Finding.rank.asc()")
    recommendations = relationship("Recommendation", back_populates="investigation", cascade="all, delete-orphan")
    feedback = relationship("InvestigationFeedback", back_populates="investigation", cascade="all, delete-orphan")

