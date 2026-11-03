from sqlalchemy import Column, String, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


class Runbook(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runbooks"

    project_id = Column(GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    code = Column(String(32), unique=True, index=True, nullable=False)  # e.g., RB-402
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    steps = Column(JSONBCompat, default=list, nullable=False)
    is_automated = Column(Boolean, default=False, nullable=False)

    project = relationship("Project", back_populates="runbooks")

