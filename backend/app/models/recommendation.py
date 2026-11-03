from sqlalchemy import Column, String, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID


class Recommendation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "recommendations"

    investigation_id = Column(GUID, ForeignKey("investigations.id", ondelete="CASCADE"), index=True, nullable=False)
    finding_id = Column(GUID, ForeignKey("findings.id", ondelete="SET NULL"), index=True, nullable=True)
    title = Column(String(256), nullable=False)
    action_type = Column(String(32), default="immediate", nullable=False)  # immediate, preventative, configuration
    description = Column(Text, nullable=False)
    command_snippet = Column(Text, nullable=True)
    risk_level = Column(String(16), default="LOW", nullable=False)         # LOW, MEDIUM, HIGH
    is_dry_run_safe = Column(Boolean, default=True, nullable=False)
    requires_human_approval = Column(Boolean, default=True, nullable=False)
    is_demo = Column(Boolean, default=True, nullable=False)

    investigation = relationship("Investigation", back_populates="recommendations")
    finding = relationship("Finding", back_populates="recommendations")

