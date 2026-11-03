from sqlalchemy import Column, String, ForeignKey, Integer, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID


class InvestigationFeedback(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "investigation_feedback"

    investigation_id = Column(GUID, ForeignKey("investigations.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(String(128), default="alex.chen@acme.corp", nullable=False)
    rating = Column(Integer, nullable=False)  # 1 to 5 stars
    comments = Column(Text, nullable=True)
    was_root_cause_accurate = Column(Boolean, default=True, nullable=False)

    investigation = relationship("Investigation", back_populates="feedback")

