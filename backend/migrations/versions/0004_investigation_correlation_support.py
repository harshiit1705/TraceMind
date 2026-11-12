"""Add correlation group link and Gemini metadata to investigations for Sprint 5.1

Revision ID: 0004_investigation_correlation_support
Revises: 0003_service_dependencies_and_correlation
Create Date: 2026-11-06 22:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004_investigation_correlation_support'
down_revision: Union[str, None] = '0003_service_dependencies_and_correlation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('investigations', schema=None) as batch_op:
        # 1. Modify incident_id to be nullable so investigations can exist independently for CorrelationGroups
        batch_op.alter_column(
            'incident_id',
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )

        # 2. Add correlation_group_id with SET NULL on delete to preserve audit history
        batch_op.add_column(
            sa.Column(
                'correlation_group_id',
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(
                    'correlation_groups.id',
                    ondelete='SET NULL',
                    name='fk_investigations_correlation_group_id',
                ),
                nullable=True,
            )
        )
        batch_op.create_index('ix_investigations_correlation_group_id', ['correlation_group_id'])

        # 3. Add AI provider and model execution metadata
        batch_op.add_column(
            sa.Column('provider', sa.String(length=64), server_default='google-gemini', nullable=False)
        )
        batch_op.add_column(
            sa.Column('model_name', sa.String(length=64), server_default='gemini-2.0-flash', nullable=False)
        )
        batch_op.add_column(
            sa.Column('prompt_version', sa.String(length=32), server_default='v1.0', nullable=False)
        )
        batch_op.add_column(
            sa.Column('schema_version', sa.String(length=32), server_default='v1.0', nullable=False)
        )

        # 4. Add validated structured investigation payload and evidence hash
        batch_op.add_column(
            sa.Column('investigation_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )
        batch_op.add_column(
            sa.Column('evidence_hash', sa.String(length=64), nullable=True)
        )
        batch_op.create_index('ix_investigations_evidence_hash', ['evidence_hash'])

        # 5. Add token usage, latency, and sanitized error tracking
        batch_op.add_column(
            sa.Column('prompt_tokens', sa.Integer(), server_default='0', nullable=False)
        )
        batch_op.add_column(
            sa.Column('completion_tokens', sa.Integer(), server_default='0', nullable=False)
        )
        batch_op.add_column(
            sa.Column('total_tokens', sa.Integer(), server_default='0', nullable=False)
        )
        batch_op.add_column(
            sa.Column('latency_ms', sa.Integer(), server_default='0', nullable=False)
        )
        batch_op.add_column(
            sa.Column('error_message', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('investigations', schema=None) as batch_op:
        batch_op.drop_column('error_message')
        batch_op.drop_column('latency_ms')
        batch_op.drop_column('total_tokens')
        batch_op.drop_column('completion_tokens')
        batch_op.drop_column('prompt_tokens')
        batch_op.drop_index('ix_investigations_evidence_hash')
        batch_op.drop_column('evidence_hash')
        batch_op.drop_column('investigation_json')
        batch_op.drop_column('schema_version')
        batch_op.drop_column('prompt_version')
        batch_op.drop_column('model_name')
        batch_op.drop_column('provider')
        batch_op.drop_index('ix_investigations_correlation_group_id')
        batch_op.drop_column('correlation_group_id')

        batch_op.alter_column(
            'incident_id',
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )

