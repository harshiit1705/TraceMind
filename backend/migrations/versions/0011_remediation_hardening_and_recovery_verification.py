"""Remediation hardening, lease support, and recovery verification schema.

Revision ID: 0011_remediation_hardening_and_recovery_verification
Revises: 0010_remediation_workflow_support
Create Date: 2026-11-13 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from app.models.base import GUID

# revision identifiers, used by Alembic.
revision: str = '0011_remediation_hardening_and_recovery_verification'
down_revision: Union[str, None] = '0010_remediation_workflow_support'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    # 1. Enhance recommendations table with project/incident ownership and lease tracking
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('incident_id', GUID(), nullable=True))
        batch_op.add_column(sa.Column('project_id', GUID(), nullable=True))
        batch_op.add_column(sa.Column('execution_started_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('execution_lease_expires_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('execution_attempt_id', sa.String(length=64), nullable=True))
        
        # Replace non-unique idempotency index with unique partial index
        batch_op.drop_index('ix_recommendations_idempotency_key')
        batch_op.create_index(
            'uq_recommendations_idempotency_key',
            ['execution_idempotency_key'],
            unique=True,
            sqlite_where=sa.text('execution_idempotency_key IS NOT NULL'),
            postgresql_where=sa.text('execution_idempotency_key IS NOT NULL'),
        )
        batch_op.create_index('ix_recommendations_incident_id', ['incident_id'], unique=False)
        batch_op.create_index('ix_recommendations_project_id', ['project_id'], unique=False)
        batch_op.create_index('ix_recommendations_execution_attempt_id', ['execution_attempt_id'], unique=False)

    # 2. Create recovery_verifications table for Phase 5
    op.create_table(
        'recovery_verifications',
        sa.Column('id', GUID(), primary_key=True),
        sa.Column('incident_id', GUID(), sa.ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('remediation_id', GUID(), sa.ForeignKey('recommendations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', GUID(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('execution_attempt_id', sa.String(length=64), nullable=True),
        sa.Column('target_service', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='PENDING', nullable=False),
        sa.Column('recovery_outcome', sa.String(length=32), nullable=True),
        sa.Column('verification_window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verification_window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sample_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('checks_summary_json', JSONType, nullable=False),
        sa.Column('evidence_snapshot_json', JSONType, nullable=False),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('verified_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_recovery_verifications_incident_id', 'recovery_verifications', ['incident_id'], unique=False)
    op.create_index('ix_recovery_verifications_remediation_id', 'recovery_verifications', ['remediation_id'], unique=False)
    op.create_index('ix_recovery_verifications_project_id', 'recovery_verifications', ['project_id'], unique=False)
    op.create_index('ix_recovery_verifications_status', 'recovery_verifications', ['status'], unique=False)
    op.create_index('ix_recovery_verifications_recovery_outcome', 'recovery_verifications', ['recovery_outcome'], unique=False)


def downgrade() -> None:
    op.drop_table('recovery_verifications')
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.drop_index('ix_recommendations_execution_attempt_id')
        batch_op.drop_index('ix_recommendations_project_id')
        batch_op.drop_index('ix_recommendations_incident_id')
        batch_op.drop_index('uq_recommendations_idempotency_key')
        batch_op.create_index('ix_recommendations_idempotency_key', ['execution_idempotency_key'], unique=False)
        batch_op.drop_column('execution_attempt_id')
        batch_op.drop_column('execution_lease_expires_at')
        batch_op.drop_column('execution_started_at')
        batch_op.drop_column('project_id')
        batch_op.drop_column('incident_id')
