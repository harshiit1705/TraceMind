from sqlalchemy import Column, String, ForeignKey, Integer, Float, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


class Finding(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "findings"

    investigation_id = Column(GUID, ForeignKey("investigations.id", ondelete="CASCADE"), index=True, nullable=False)
    rank = Column(Integer, default=1, nullable=False)
    title = Column(String(256), nullable=False)
    probable_root_cause = Column(Text, nullable=False)
    explanation = Column(Text, nullable=False)
    status = Column(String(32), default="HYPOTHESIS", nullable=False)  # CONFIRMED, HYPOTHESIS, DISPROVED
    confidence_score = Column(Float, default=0.0, nullable=False)
    affected_services = Column(JSONBCompat, default=list, nullable=False)
    supporting_evidence_ids = Column(JSONBCompat, default=list, nullable=False)
    is_demo = Column(Boolean, default=True, nullable=False)

    investigation = relationship("Investigation", back_populates="findings")
    recommendations = relationship("Recommendation", back_populates="finding")

