"""Add correlation_group_id to incidents for Sprint 5.4 Phase 1

Revision ID: 0005_incident_correlation_link
Revises: 0004_investigation_correlation_support
Create Date: 2026-11-08 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005_incident_correlation_link'
down_revision: Union[str, None] = '0004_investigation_correlation_support'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'correlation_group_id',
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(
                    'correlation_groups.id',
                    ondelete='SET NULL',
                    name='fk_incidents_correlation_group_id',
                ),
                nullable=True,
            )
        )
        batch_op.create_index(
            'ix_incidents_correlation_group_id',
            ['correlation_group_id'],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.drop_index('ix_incidents_correlation_group_id')
        batch_op.drop_column('correlation_group_id')
