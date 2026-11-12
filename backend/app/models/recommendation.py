from sqlalchemy import Column, String, ForeignKey, Boolean, Text, DateTime
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import UUIDMixin, TimestampMixin, GUID, JSONBCompat


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

    # Phase 4 Lifecycle & Remediation Workflow fields
    # Lifecycle: PROPOSED, APPROVED, REJECTED, EXECUTING, EXECUTED, FAILED, CANCELLED
    status = Column(String(32), default="PROPOSED", server_default="PROPOSED", index=True, nullable=False)
    target_service = Column(String(128), nullable=True)
    action_name = Column(String(64), nullable=True)
    action_parameters = Column(JSONBCompat, default=dict, nullable=True)
    preconditions = Column(JSONBCompat, default=list, nullable=True)
    rollback_procedure = Column(Text, nullable=True)
    expected_result = Column(Text, nullable=True)
    verification_steps = Column(JSONBCompat, default=list, nullable=True)

    # Human Approval Fields
    approved_by = Column(String(128), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approval_notes = Column(Text, nullable=True)
    rejected_by = Column(String(128), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Safe Execution Fields
    executed_by = Column(String(128), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    execution_mode = Column(String(32), nullable=True)  # REAL, SIMULATED
    execution_idempotency_key = Column(String(64), nullable=True, index=True)
    execution_result_json = Column(JSONBCompat, nullable=True)
    execution_error = Column(Text, nullable=True)

    investigation = relationship("Investigation", back_populates="recommendations")
    finding = relationship("Finding", back_populates="recommendations")
