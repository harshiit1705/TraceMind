from sqlalchemy import Column, String, DateTime, ForeignKey, Float, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


class Evidence(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "evidence"

    incident_id = Column(GUID, ForeignKey("incidents.id", ondelete="CASCADE"), index=True, nullable=False)
    investigation_id = Column(GUID, ForeignKey("investigations.id", ondelete="SET NULL"), index=True, nullable=True)
    evidence_key = Column(String(64), index=True, nullable=True)  # e.g., ev-101-db-pool
    evidence_type = Column(String(32), index=True, nullable=False)  # metric, log, trace, topology
    service_identifier = Column(String(128), index=True, nullable=False)
    title = Column(String(256), nullable=False)
    observation = Column(Text, nullable=False)
    confidence_weight = Column(Float, default=1.0, nullable=False)
    timestamp = Column(DateTime(timezone=True), index=True, nullable=False)
    payload = Column(JSONBCompat, default=dict, nullable=False)
    is_demo = Column(Boolean, default=True, nullable=False)

    incident = relationship("Incident", back_populates="evidence_items")
    investigation = relationship("Investigation", back_populates="evidence_items")
