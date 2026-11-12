"""Add multi_signal_evidence_json snapshot support on correlation_groups for Phase 2 RCA.

Revision ID: 0009_multi_signal_rca_support
Revises: 0008_distributed_trace_spans_table
Create Date: 2026-11-11 23:26:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0009_multi_signal_rca_support'
down_revision: Union[str, None] = '0008_distributed_trace_spans_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.add_column(
        'correlation_groups',
        sa.Column('multi_signal_evidence_json', JSONType, nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table('correlation_groups', schema=None) as batch_op:
        batch_op.drop_column('multi_signal_evidence_json')

