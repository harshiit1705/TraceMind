"""Add anomaly baselines and events tables for Sprint 3 persistence

Revision ID: 0002_anomaly_persistence
Revises: 0001_initial_schema
Create Date: 2026-11-05 13:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0002_anomaly_persistence'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. anomaly_baselines
    op.create_table(
        'anomaly_baselines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric_name', sa.String(length=64), nullable=False),
        sa.Column('detection_method', sa.String(length=32), nullable=False),
        sa.Column('config_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('baseline_state', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('sample_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_event_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('project_id', 'service_id', 'metric_name', name='uq_project_service_metric_baseline'),
    )
    op.create_index('ix_anomaly_baselines_project_id', 'anomaly_baselines', ['project_id'])
    op.create_index('ix_anomaly_baselines_service_id', 'anomaly_baselines', ['service_id'])
    op.create_index('ix_anomaly_baselines_metric_name', 'anomaly_baselines', ['metric_name'])
    op.create_index('ix_anomaly_baselines_lookup', 'anomaly_baselines', ['project_id', 'service_id', 'metric_name'])

    # 2. anomaly_events
    op.create_table(
        'anomaly_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric_name', sa.String(length=64), nullable=False),
        sa.Column('observed_value', sa.Float(), nullable=False),
        sa.Column('expected_baseline', sa.Float(), nullable=True),
        sa.Column('deviation_pct', sa.Float(), nullable=True),
        sa.Column('severity', sa.String(length=32), nullable=False),
        sa.Column('detection_method', sa.String(length=32), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='OPEN', nullable=False),
        sa.Column('source_event_id', sa.String(length=128), nullable=True),
        sa.Column('explanation', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_anomaly_events_project_id', 'anomaly_events', ['project_id'])
    op.create_index('ix_anomaly_events_service_id', 'anomaly_events', ['service_id'])
    op.create_index('ix_anomaly_events_metric_name', 'anomaly_events', ['metric_name'])
    op.create_index('ix_anomaly_events_occurred_at', 'anomaly_events', ['occurred_at'])
    op.create_index('ix_anomaly_events_source_event_id', 'anomaly_events', ['source_event_id'])
    op.create_index('ix_anomaly_events_service_metric_occurred', 'anomaly_events', ['project_id', 'service_id', 'metric_name', 'occurred_at'])
    op.create_index(
        'uq_anomaly_events_source_event_id',
        'anomaly_events',
        ['project_id', 'service_id', 'metric_name', 'source_event_id'],
        unique=True,
        postgresql_where=sa.text('source_event_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_table('anomaly_events')
    op.drop_table('anomaly_baselines')

