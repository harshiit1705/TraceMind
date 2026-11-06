from sqlalchemy import Column, String, Integer, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


class Service(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "services"

    project_id = Column(GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    slug = Column(String(64), index=True, nullable=False)
    name = Column(String(128), nullable=False)
    identifier = Column(String(128), index=True, nullable=False)
    tier = Column(Integer, default=1, nullable=False)  # 0, 1, 2
    owner_team = Column(String(128), default="Platform Core", nullable=False)
    status = Column(String(32), default="healthy", nullable=False)  # healthy, degraded, unhealthy
    request_rate_rps = Column(Float, default=0.0, nullable=False)
    error_rate_percent = Column(Float, default=0.0, nullable=False)
    p95_latency_ms = Column(Float, default=0.0, nullable=False)
    metadata_json = Column(JSONBCompat, default=dict, nullable=False)

    project = relationship("Project", back_populates="services")
    anomaly_baselines = relationship("AnomalyBaseline", back_populates="service", cascade="all, delete-orphan")
    anomaly_events = relationship("AnomalyEvent", back_populates="service", cascade="all, delete-orphan")
    upstream_dependencies = relationship(
        "ServiceDependency",
        foreign_keys="ServiceDependency.source_service_id",
        back_populates="source_service",
        cascade="all, delete-orphan",
    )
    downstream_dependents = relationship(
        "ServiceDependency",
        foreign_keys="ServiceDependency.target_service_id",
        back_populates="target_service",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_project_service_slug"),
    )

