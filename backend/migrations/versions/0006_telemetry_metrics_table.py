"""Add metric_samples table for Sprint 6 Milestone 6.1 metrics persistence

Revision ID: 0006_telemetry_metrics_table
Revises: 0005_incident_correlation_link
Create Date: 2026-11-11 12:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006_telemetry_metrics_table'
down_revision: Union[str, None] = '0005_incident_correlation_link'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUIDType = sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), 'postgresql')
JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'metric_samples',
        sa.Column('id', UUIDType, primary_key=True, nullable=False),
        sa.Column('project_id', UUIDType, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_id', UUIDType, sa.ForeignKey('services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric_name', sa.String(length=64), nullable=False),
        sa.Column('metric_unit', sa.String(length=32), server_default='', nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('endpoint', sa.String(length=256), nullable=True),
        sa.Column('http_status_code', sa.Integer(), nullable=True),
        sa.Column('request_id', sa.String(length=128), nullable=True),
        sa.Column('trace_id', sa.String(length=64), nullable=True),
        sa.Column('source_event_id', sa.String(length=128), nullable=True),
        sa.Column('attributes_json', JSONType, server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_metric_samples_project_id', 'metric_samples', ['project_id'])
    op.create_index('ix_metric_samples_service_id', 'metric_samples', ['service_id'])
    op.create_index('ix_metric_samples_timestamp', 'metric_samples', ['timestamp'])
    op.create_index('ix_metric_samples_request_id', 'metric_samples', ['request_id'])
    op.create_index('ix_metric_samples_trace_id', 'metric_samples', ['trace_id'])
    op.create_index(
        'ix_metric_samples_lookup',
        'metric_samples',
        ['project_id', 'service_id', 'metric_name', 'timestamp'],
    )
    op.create_index(
        'ix_metric_samples_project_time',
        'metric_samples',
        ['project_id', 'timestamp'],
    )
    op.create_index(
        'uq_metric_samples_source_event_id',
        'metric_samples',
        ['project_id', 'service_id', 'metric_name', 'source_event_id'],
        unique=True,
        postgresql_where=sa.text('source_event_id IS NOT NULL'),
        sqlite_where=sa.text('source_event_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_metric_samples_source_event_id', table_name='metric_samples')
    op.drop_index('ix_metric_samples_project_time', table_name='metric_samples')
    op.drop_index('ix_metric_samples_lookup', table_name='metric_samples')
    op.drop_index('ix_metric_samples_trace_id', table_name='metric_samples')
    op.drop_index('ix_metric_samples_request_id', table_name='metric_samples')
    op.drop_index('ix_metric_samples_timestamp', table_name='metric_samples')
    op.drop_index('ix_metric_samples_service_id', table_name='metric_samples')
    op.drop_index('ix_metric_samples_project_id', table_name='metric_samples')
    op.drop_table('metric_samples')

