from sqlalchemy import Column, String
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, JSONBCompat


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    slug = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    tier = Column(String(32), default="enterprise", nullable=False)
    settings_json = Column(JSONBCompat, default=dict, nullable=False)

    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan")

