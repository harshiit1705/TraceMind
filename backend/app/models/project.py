from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID


class Project(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "projects"

    organization_id = Column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    environment = Column(String(32), default="production", nullable=False)
    description = Column(String(512), nullable=True)

    organization = relationship("Organization", back_populates="projects")
    services = relationship("Service", back_populates="project", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="project", cascade="all, delete-orphan")
    runbooks = relationship("Runbook", back_populates="project", cascade="all, delete-orphan")

