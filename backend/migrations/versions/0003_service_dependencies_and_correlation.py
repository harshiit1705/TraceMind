"""Add service dependencies and correlation persistence tables for Sprint 4

Revision ID: 0003_service_dependencies_and_correlation
Revises: 0002_anomaly_persistence
Create Date: 2026-11-05 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003_service_dependencies_and_correlation'
down_revision: Union[str, None] = '0002_anomaly_persistence'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. service_dependencies
    op.create_table(
        'service_dependencies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_service_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_service_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('dependency_type', sa.String(length=32), server_default='sync', nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('project_id', 'source_service_id', 'target_service_id', name='uq_service_dependencies_project_source_target'),
        sa.CheckConstraint('source_service_id != target_service_id', name='ck_service_dependencies_no_self'),
    )
    op.create_index('ix_service_dependencies_project_id', 'service_dependencies', ['project_id'])
    op.create_index('ix_service_dependencies_source_service_id', 'service_dependencies', ['source_service_id'])
    op.create_index('ix_service_dependencies_target_service_id', 'service_dependencies', ['target_service_id'])

    # 2. correlation_groups
    op.create_table(
        'correlation_groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('correlation_key', sa.String(length=128), nullable=False),
        sa.Column('time_window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('time_window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='ACTIVE', nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('confidence_score', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('topology_complete', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('project_id', 'correlation_key', name='uq_project_correlation_key'),
    )
    op.create_index('ix_correlation_groups_project_id', 'correlation_groups', ['project_id'])
    op.create_index('ix_correlation_groups_correlation_key', 'correlation_groups', ['correlation_key'])
    op.create_index('ix_correlation_groups_time_window_start', 'correlation_groups', ['time_window_start'])
    op.create_index('ix_correlation_groups_time_window_end', 'correlation_groups', ['time_window_end'])

    # 3. correlation_group_events
    op.create_table(
        'correlation_group_events',
        sa.Column('correlation_group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('correlation_groups.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('anomaly_event_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('anomaly_events.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('relevance_score', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('correlation_reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 4. root_cause_candidates
    op.create_table(
        'root_cause_candidates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('correlation_group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('correlation_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('service_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('services.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('confidence', sa.String(length=32), nullable=False),
        sa.Column('is_probable_root_cause', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('temporal_precedence_score', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('topological_score', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('blast_radius_score', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('severity_score', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('reasons_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('correlation_group_id', 'service_id', name='uq_correlation_group_service_candidate'),
        sa.UniqueConstraint('correlation_group_id', 'rank', name='uq_correlation_group_candidate_rank'),
    )
    op.create_index('ix_root_cause_candidates_correlation_group_id', 'root_cause_candidates', ['correlation_group_id'])
    op.create_index('ix_root_cause_candidates_service_id', 'root_cause_candidates', ['service_id'])


def downgrade() -> None:
    op.drop_table('root_cause_candidates')
    op.drop_table('correlation_group_events')
    op.drop_table('correlation_groups')
    op.drop_table('service_dependencies')

