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
    # 1. Modify incident_id to be nullable so investigations can exist independently for CorrelationGroups
    op.alter_column(
        'investigations',
        'incident_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # 2. Add correlation_group_id with SET NULL on delete to preserve audit history
    op.add_column(
        'investigations',
        sa.Column(
            'correlation_group_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('correlation_groups.id', ondelete='SET NULL'),
            nullable=True,
        )
    )
    op.create_index('ix_investigations_correlation_group_id', 'investigations', ['correlation_group_id'])

    # 3. Add AI provider and model execution metadata
    op.add_column(
        'investigations',
        sa.Column('provider', sa.String(length=64), server_default='google-gemini', nullable=False)
    )
    op.add_column(
        'investigations',
        sa.Column('model_name', sa.String(length=64), server_default='gemini-2.0-flash', nullable=False)
    )
    op.add_column(
        'investigations',
        sa.Column('prompt_version', sa.String(length=32), server_default='v1.0', nullable=False)
    )
    op.add_column(
        'investigations',
        sa.Column('schema_version', sa.String(length=32), server_default='v1.0', nullable=False)
    )

    # 4. Add validated structured investigation payload and evidence hash
    op.add_column(
        'investigations',
        sa.Column('investigation_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        'investigations',
        sa.Column('evidence_hash', sa.String(length=64), nullable=True)
    )
    op.create_index('ix_investigations_evidence_hash', 'investigations', ['evidence_hash'])

    # 5. Add token usage, latency, and sanitized error tracking
    op.add_column(
        'investigations',
        sa.Column('prompt_tokens', sa.Integer(), server_default='0', nullable=False)
    )
    op.add_column(
        'investigations',
        sa.Column('completion_tokens', sa.Integer(), server_default='0', nullable=False)
    )
    op.add_column(
        'investigations',
        sa.Column('total_tokens', sa.Integer(), server_default='0', nullable=False)
    )
    op.add_column(
        'investigations',
        sa.Column('latency_ms', sa.Integer(), server_default='0', nullable=False)
    )
    op.add_column(
        'investigations',
        sa.Column('error_message', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('investigations', 'error_message')
    op.drop_column('investigations', 'latency_ms')
    op.drop_column('investigations', 'total_tokens')
    op.drop_column('investigations', 'completion_tokens')
    op.drop_column('investigations', 'prompt_tokens')
    op.drop_index('ix_investigations_evidence_hash', 'investigations')
    op.drop_column('investigations', 'evidence_hash')
    op.drop_column('investigations', 'investigation_json')
    op.drop_column('investigations', 'schema_version')
    op.drop_column('investigations', 'prompt_version')
    op.drop_column('investigations', 'model_name')
    op.drop_column('investigations', 'provider')
    op.drop_index('ix_investigations_correlation_group_id', 'investigations')
    op.drop_column('investigations', 'correlation_group_id')

    op.alter_column(
        'investigations',
        'incident_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

