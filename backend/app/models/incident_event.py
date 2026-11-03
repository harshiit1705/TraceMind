from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


class IncidentEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "incident_events"

    incident_id = Column(GUID, ForeignKey("incidents.id", ondelete="CASCADE"), index=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), index=True, nullable=False)
    title = Column(String(256), nullable=False)
    event_type = Column(String(32), default="alert", nullable=False)  # anomaly, alert, agent, human, action
    source = Column(String(128), default="system", nullable=False)
    description = Column(Text, nullable=False)
    payload = Column(JSONBCompat, default=dict, nullable=True)

    incident = relationship("Incident", back_populates="events")

