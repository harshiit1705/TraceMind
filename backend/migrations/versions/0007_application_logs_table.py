"""Add application_logs table for Sprint 6 Milestone 6.2 structured logging

Revision ID: 0007_application_logs_table
Revises: 0006_telemetry_metrics_table
Create Date: 2026-11-11 12:46:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0007_application_logs_table'
down_revision: Union[str, None] = '0006_telemetry_metrics_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUIDType = sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), 'postgresql')
JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'application_logs',
        sa.Column('id', UUIDType, primary_key=True, nullable=False),
        sa.Column('project_id', UUIDType, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_id', UUIDType, sa.ForeignKey('services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('request_id', sa.String(length=128), nullable=True),
        sa.Column('trace_id', sa.String(length=64), nullable=True),
        sa.Column('span_id', sa.String(length=32), nullable=True),
        sa.Column('source_event_id', sa.String(length=128), nullable=True),
        sa.Column('attributes_json', JSONType, server_default='{}', nullable=False),
        sa.Column('exception_type', sa.String(length=128), nullable=True),
        sa.Column('exception_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_application_logs_project_id', 'application_logs', ['project_id'])
    op.create_index('ix_application_logs_service_id', 'application_logs', ['service_id'])
    op.create_index('ix_application_logs_timestamp', 'application_logs', ['timestamp'])
    op.create_index('ix_application_logs_request_id', 'application_logs', ['request_id'])
    op.create_index('ix_application_logs_trace_id', 'application_logs', ['trace_id'])
    op.create_index('ix_application_logs_span_id', 'application_logs', ['span_id'])
    op.create_index(
        'ix_application_logs_query',
        'application_logs',
        ['project_id', 'service_id', 'level', 'timestamp'],
    )
    op.create_index(
        'ix_application_logs_trace',
        'application_logs',
        ['project_id', 'trace_id', 'timestamp'],
    )
    op.create_index(
        'uq_application_logs_source_event_id',
        'application_logs',
        ['project_id', 'service_id', 'source_event_id'],
        unique=True,
        postgresql_where=sa.text('source_event_id IS NOT NULL'),
        sqlite_where=sa.text('source_event_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_application_logs_source_event_id', table_name='application_logs')
    op.drop_index('ix_application_logs_trace', table_name='application_logs')
    op.drop_index('ix_application_logs_query', table_name='application_logs')
    op.drop_index('ix_application_logs_span_id', table_name='application_logs')
    op.drop_index('ix_application_logs_trace_id', table_name='application_logs')
    op.drop_index('ix_application_logs_request_id', table_name='application_logs')
    op.drop_index('ix_application_logs_timestamp', table_name='application_logs')
    op.drop_index('ix_application_logs_service_id', table_name='application_logs')
    op.drop_index('ix_application_logs_project_id', table_name='application_logs')
    op.drop_table('application_logs')

