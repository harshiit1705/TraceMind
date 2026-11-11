"""Add trace_spans table for Sprint 6 Milestone 6.3 distributed tracing

Revision ID: 0008_distributed_trace_spans_table
Revises: 0007_application_logs_table
Create Date: 2026-11-11 12:47:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0008_distributed_trace_spans_table'
down_revision: Union[str, None] = '0007_application_logs_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUIDType = sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), 'postgresql')
JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'trace_spans',
        sa.Column('id', UUIDType, primary_key=True, nullable=False),
        sa.Column('project_id', UUIDType, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_id', UUIDType, sa.ForeignKey('services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('trace_id', sa.String(length=64), nullable=False),
        sa.Column('span_id', sa.String(length=32), nullable=False),
        sa.Column('parent_span_id', sa.String(length=32), nullable=True),
        sa.Column('operation_name', sa.String(length=256), nullable=False),
        sa.Column('span_kind', sa.String(length=16), server_default='server', nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_ms', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='ok', nullable=False),
        sa.Column('http_status_code', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('request_id', sa.String(length=128), nullable=True),
        sa.Column('attributes_json', JSONType, server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('project_id', 'trace_id', 'span_id', name='uq_project_trace_span'),
    )
    op.create_index('ix_trace_spans_project_id', 'trace_spans', ['project_id'])
    op.create_index('ix_trace_spans_service_id', 'trace_spans', ['service_id'])
    op.create_index('ix_trace_spans_trace_id', 'trace_spans', ['trace_id'])
    op.create_index('ix_trace_spans_parent_span_id', 'trace_spans', ['parent_span_id'])
    op.create_index('ix_trace_spans_start_time', 'trace_spans', ['start_time'])
    op.create_index('ix_trace_spans_request_id', 'trace_spans', ['request_id'])
    op.create_index('ix_trace_spans_trace_lookup', 'trace_spans', ['project_id', 'trace_id', 'start_time'])
    op.create_index('ix_trace_spans_service_time', 'trace_spans', ['project_id', 'service_id', 'start_time'])
    op.create_index('ix_trace_spans_root_list', 'trace_spans', ['project_id', 'parent_span_id', 'start_time'])


def downgrade() -> None:
    op.drop_index('ix_trace_spans_root_list', table_name='trace_spans')
    op.drop_index('ix_trace_spans_service_time', table_name='trace_spans')
    op.drop_index('ix_trace_spans_trace_lookup', table_name='trace_spans')
    op.drop_index('ix_trace_spans_request_id', table_name='trace_spans')
    op.drop_index('ix_trace_spans_start_time', table_name='trace_spans')
    op.drop_index('ix_trace_spans_parent_span_id', table_name='trace_spans')
    op.drop_index('ix_trace_spans_trace_id', table_name='trace_spans')
    op.drop_index('ix_trace_spans_service_id', table_name='trace_spans')
    op.drop_index('ix_trace_spans_project_id', table_name='trace_spans')
    op.drop_table('trace_spans')

