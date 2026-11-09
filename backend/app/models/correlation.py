"""SQLAlchemy models for persisting correlation groups, event associations, and ranked root causes."""

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


class CorrelationGroup(Base, UUIDMixin, TimestampMixin):
    """Represents a set of cross-service anomaly events correlated within a time window."""

    __tablename__ = "correlation_groups"

    project_id = Column(
        GUID,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    correlation_key = Column(
        String(128),
        index=True,
        nullable=False,
    )  # Deterministic hash of project + sorted anomaly event IDs to guarantee idempotency
    time_window_start = Column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )
    time_window_end = Column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )
    status = Column(
        String(32),
        default="ACTIVE",
        nullable=False,
    )  # ACTIVE, INVESTIGATING, MITIGATED, RESOLVED, DISMISSED
    summary = Column(
        Text,
        nullable=True,
    )
    confidence_score = Column(
        Float,
        default=0.0,
        nullable=False,
    )  # Normalized 0.0 - 1.0 confidence in the overall correlation
    topology_complete = Column(
        Boolean,
        default=True,
        nullable=False,
    )  # False if one or more services in group lacked registered dependency graph edges

    # Relationships
    project = relationship("Project")
    event_associations = relationship(
        "CorrelationEventAssociation",
        back_populates="correlation_group",
        cascade="all, delete-orphan",
        order_by="CorrelationEventAssociation.created_at",
    )
    root_cause_candidates = relationship(
        "RootCauseCandidate",
        back_populates="correlation_group",
        cascade="all, delete-orphan",
        order_by="RootCauseCandidate.rank",
    )
    investigations = relationship(
        "Investigation",
        back_populates="correlation_group",
    )
    incidents = relationship(
        "Incident",
        back_populates="correlation_group",
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "correlation_key",
            name="uq_project_correlation_key",
        ),
    )


class CorrelationEventAssociation(Base, TimestampMixin):
    """Join table associating anomaly events with a correlation group with inclusion rationale."""

    __tablename__ = "correlation_group_events"

    correlation_group_id = Column(
        GUID,
        ForeignKey("correlation_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    anomaly_event_id = Column(
        GUID,
        ForeignKey("anomaly_events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relevance_score = Column(
        Float,
        default=1.0,
        nullable=False,
    )
    correlation_reason = Column(
        Text,
        nullable=False,
    )

    # Relationships
    correlation_group = relationship(
        "CorrelationGroup",
        back_populates="event_associations",
    )
    anomaly_event = relationship("AnomalyEvent")


class RootCauseCandidate(Base, UUIDMixin, TimestampMixin):
    """Persisted root-cause candidate evaluation for a service in a correlation group."""

    __tablename__ = "root_cause_candidates"

    correlation_group_id = Column(
        GUID,
        ForeignKey("correlation_groups.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    service_id = Column(
        GUID,
        ForeignKey("services.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    rank = Column(
        Integer,
        nullable=False,
    )  # 1 = top probable root cause
    score = Column(
        Float,
        nullable=False,
    )  # Deterministic composite score (0.0 - 1.0)
    confidence = Column(
        String(32),
        nullable=False,
    )  # HIGH, MEDIUM, LOW
    is_probable_root_cause = Column(
        Boolean,
        default=False,
        nullable=False,
    )  # True for highest-ranked candidate(s); explicitly unconfirmed

    # Normalized dimension breakdown (each 0.0 - 1.0)
    temporal_precedence_score = Column(
        Float,
        default=0.0,
        nullable=False,
    )
    topological_score = Column(
        Float,
        default=0.0,
        nullable=False,
    )
    blast_radius_score = Column(
        Float,
        default=0.0,
        nullable=False,
    )
    severity_score = Column(
        Float,
        default=0.0,
        nullable=False,
    )

    # Detailed human-readable explainability payload
    reasons_json = Column(
        JSONBCompat,
        default=dict,
        nullable=False,
    )

    # Relationships
    correlation_group = relationship(
        "CorrelationGroup",
        back_populates="root_cause_candidates",
    )
    service = relationship("Service")

    __table_args__ = (
        UniqueConstraint(
            "correlation_group_id",
            "service_id",
            name="uq_correlation_group_service_candidate",
        ),
        UniqueConstraint(
            "correlation_group_id",
            "rank",
            name="uq_correlation_group_candidate_rank",
        ),
    )

