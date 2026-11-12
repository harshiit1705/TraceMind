"""Add remediation workflow and human approval lifecycle support to recommendations table.

Revision ID: 0010_remediation_workflow_support
Revises: 0009_multi_signal_rca_support
Create Date: 2026-11-13 02:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0010_remediation_workflow_support'
down_revision: Union[str, None] = '0009_multi_signal_rca_support'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=32), server_default='PROPOSED', nullable=False))
        batch_op.add_column(sa.Column('target_service', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('action_name', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('action_parameters', JSONType, nullable=True))
        batch_op.add_column(sa.Column('preconditions', JSONType, nullable=True))
        batch_op.add_column(sa.Column('rollback_procedure', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('expected_result', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('verification_steps', JSONType, nullable=True))
        batch_op.add_column(sa.Column('approved_by', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('approval_notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('rejected_by', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('rejection_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('executed_by', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('execution_mode', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('execution_idempotency_key', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('execution_result_json', JSONType, nullable=True))
        batch_op.add_column(sa.Column('execution_error', sa.Text(), nullable=True))
        batch_op.create_index('ix_recommendations_status', ['status'], unique=False)
        batch_op.create_index('ix_recommendations_idempotency_key', ['execution_idempotency_key'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.drop_index('ix_recommendations_idempotency_key')
        batch_op.drop_index('ix_recommendations_status')
        batch_op.drop_column('execution_error')
        batch_op.drop_column('execution_result_json')
        batch_op.drop_column('execution_idempotency_key')
        batch_op.drop_column('execution_mode')
        batch_op.drop_column('executed_at')
        batch_op.drop_column('executed_by')
        batch_op.drop_column('rejection_reason')
        batch_op.drop_column('rejected_at')
        batch_op.drop_column('rejected_by')
        batch_op.drop_column('approval_notes')
        batch_op.drop_column('approved_at')
        batch_op.drop_column('approved_by')
        batch_op.drop_column('verification_steps')
        batch_op.drop_column('expected_result')
        batch_op.drop_column('rollback_procedure')
        batch_op.drop_column('preconditions')
        batch_op.drop_column('action_parameters')
        batch_op.drop_column('action_name')
        batch_op.drop_column('target_service')
        batch_op.drop_column('status')

