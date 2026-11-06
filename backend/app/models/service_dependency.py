"""SQLAlchemy model representing directed service dependencies within a project boundary."""

from datetime import datetime, timezone
from sqlalchemy import Column, String, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID


class ServiceDependency(Base, UUIDMixin, TimestampMixin):
    """Represents a directed dependency edge from a caller (downstream) to a callee (upstream).
    
    Semantics:
    - `source_service_id` (caller / dependent / downstream): The service that makes calls.
    - `target_service_id` (callee / dependency / upstream): The service that provides the capability.
    
    Example:
    If Order Service calls Inventory Service:
    `source_service_id` = Order Service (downstream)
    `target_service_id` = Inventory Service (upstream)
    """

    __tablename__ = "service_dependencies"

    project_id = Column(
        GUID,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_service_id = Column(
        GUID,
        ForeignKey("services.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    target_service_id = Column(
        GUID,
        ForeignKey("services.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    dependency_type = Column(
        String(32),
        default="sync",
        nullable=False,
    )  # sync (HTTP/gRPC), async (message/queue), database, cache, third_party
    description = Column(
        String(255),
        nullable=True,
    )

    # Relationships
    project = relationship("Project")
    source_service = relationship(
        "Service",
        foreign_keys=[source_service_id],
        back_populates="upstream_dependencies",
    )
    target_service = relationship(
        "Service",
        foreign_keys=[target_service_id],
        back_populates="downstream_dependents",
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_service_id",
            "target_service_id",
            name="uq_service_dependencies_project_source_target",
        ),
        CheckConstraint(
            "source_service_id != target_service_id",
            name="ck_service_dependencies_no_self",
        ),
    )

    @property
    def downstream_service_id(self):
        """Alias: caller / dependent."""
        return self.source_service_id

    @property
    def upstream_service_id(self):
        """Alias: callee / dependency."""
        return self.target_service_id

