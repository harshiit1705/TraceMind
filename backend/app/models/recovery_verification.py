"""Recovery Verification ORM Model.

Stores historical evidence-grounded verification results comparing post-remediation
telemetry against historical baselines to confirm service recovery.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.models.base import GUID, JSONBCompat, TimestampMixin, UUIDMixin


class RecoveryVerification(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "recovery_verifications"

    incident_id = Column(GUID, ForeignKey("incidents.id", ondelete="CASCADE"), index=True, nullable=False)
    remediation_id = Column(GUID, ForeignKey("recommendations.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id = Column(GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    execution_attempt_id = Column(String(64), nullable=True, index=True)
    target_service = Column(String(128), nullable=False, index=True)

    # Verification process lifecycle: PENDING, RUNNING, COMPLETED, FAILED
    status = Column(String(32), default="PENDING", server_default="PENDING", index=True, nullable=False)

    # Actual telemetry-proven outcome: RECOVERED, NOT_RECOVERED, PARTIALLY_RECOVERED, INCONCLUSIVE
    recovery_outcome = Column(String(32), nullable=True, index=True)

    verification_window_start = Column(DateTime(timezone=True), nullable=False)
    verification_window_end = Column(DateTime(timezone=True), nullable=False)
    sample_count = Column(Integer, default=0, nullable=False)

    checks_summary_json = Column(JSONBCompat, default=list, nullable=False)
    evidence_snapshot_json = Column(JSONBCompat, default=dict, nullable=False)

    explanation = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    verified_by = Column(String(128), nullable=True)

    incident = relationship("Incident", backref="recovery_verifications")
    remediation = relationship("Recommendation", backref="recovery_verifications")
    project = relationship("Project", backref="recovery_verifications")
