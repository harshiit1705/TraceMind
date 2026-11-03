"""Initial schema for TraceMind backend matching finalized SQLAlchemy models

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-11-02 23:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. organizations
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('slug', sa.String(length=64), nullable=False, unique=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('tier', sa.String(length=32), server_default='enterprise', nullable=False),
        sa.Column('settings_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_organizations_slug', 'organizations', ['slug'])

    # 2. projects
    op.create_table(
        'projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False, unique=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('environment', sa.String(length=32), server_default='production', nullable=False),
        sa.Column('description', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_projects_organization_id', 'projects', ['organization_id'])
    op.create_index('ix_projects_slug', 'projects', ['slug'])

    # 3. services
    op.create_table(
        'services',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('identifier', sa.String(length=128), nullable=False),
        sa.Column('tier', sa.Integer(), server_default='1', nullable=False),
        sa.Column('owner_team', sa.String(length=128), server_default='Platform Core', nullable=False),
        sa.Column('status', sa.String(length=32), server_default='healthy', nullable=False),
        sa.Column('request_rate_rps', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('error_rate_percent', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('p95_latency_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('project_id', 'slug', name='uq_project_service_slug'),
    )
    op.create_index('ix_services_project_id', 'services', ['project_id'])
    op.create_index('ix_services_slug', 'services', ['slug'])
    op.create_index('ix_services_identifier', 'services', ['identifier'])

    # 4. incidents
    op.create_table(
        'incidents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('incident_number', sa.String(length=32), nullable=False, unique=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('severity', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('mitigated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('commander_name', sa.String(length=128), server_default='Alex Chen', nullable=False),
        sa.Column('commander_role', sa.String(length=128), server_default='Staff SRE', nullable=False),
        sa.Column('root_cause_summary', sa.Text(), nullable=True),
        sa.Column('affected_services', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('is_demo', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_incidents_project_id', 'incidents', ['project_id'])
    op.create_index('ix_incidents_incident_number', 'incidents', ['incident_number'])
    op.create_index('ix_incidents_severity', 'incidents', ['severity'])
    op.create_index('ix_incidents_status', 'incidents', ['status'])

    # 5. incident_events
    op.create_table(
        'incident_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('incident_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('event_type', sa.String(length=32), server_default='alert', nullable=False),
        sa.Column('source', sa.String(length=128), server_default='system', nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_incident_events_incident_id', 'incident_events', ['incident_id'])
    op.create_index('ix_incident_events_timestamp', 'incident_events', ['timestamp'])

    # 6. investigations
    op.create_table(
        'investigations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('incident_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_name', sa.String(length=128), server_default='Autonomous Agent #4', nullable=False),
        sa.Column('status', sa.String(length=32), server_default='COMPLETED', nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('correlation_scope', sa.Integer(), server_default='0', nullable=False),
        sa.Column('spans_analyzed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('is_demo', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_investigations_incident_id', 'investigations', ['incident_id'])
    op.create_index('ix_investigations_status', 'investigations', ['status'])

    # 7. evidence
    op.create_table(
        'evidence',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('incident_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('investigation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('investigations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('evidence_key', sa.String(length=64), nullable=True),
        sa.Column('evidence_type', sa.String(length=32), nullable=False),
        sa.Column('service_identifier', sa.String(length=128), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('observation', sa.Text(), nullable=False),
        sa.Column('confidence_weight', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('is_demo', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_evidence_incident_id', 'evidence', ['incident_id'])
    op.create_index('ix_evidence_investigation_id', 'evidence', ['investigation_id'])
    op.create_index('ix_evidence_evidence_key', 'evidence', ['evidence_key'])
    op.create_index('ix_evidence_evidence_type', 'evidence', ['evidence_type'])
    op.create_index('ix_evidence_service_identifier', 'evidence', ['service_identifier'])
    op.create_index('ix_evidence_timestamp', 'evidence', ['timestamp'])

    # 8. findings
    op.create_table(
        'findings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('investigation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('investigations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rank', sa.Integer(), server_default='1', nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('probable_root_cause', sa.Text(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='HYPOTHESIS', nullable=False),
        sa.Column('confidence_score', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('affected_services', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('supporting_evidence_ids', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('is_demo', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_findings_investigation_id', 'findings', ['investigation_id'])

    # 9. recommendations
    op.create_table(
        'recommendations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('investigation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('investigations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('finding_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('findings.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('action_type', sa.String(length=32), server_default='immediate', nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('command_snippet', sa.Text(), nullable=True),
        sa.Column('risk_level', sa.String(length=16), server_default='LOW', nullable=False),
        sa.Column('is_dry_run_safe', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('requires_human_approval', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_demo', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_recommendations_investigation_id', 'recommendations', ['investigation_id'])
    op.create_index('ix_recommendations_finding_id', 'recommendations', ['finding_id'])

    # 10. runbooks
    op.create_table(
        'runbooks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False, unique=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('is_automated', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_runbooks_project_id', 'runbooks', ['project_id'])
    op.create_index('ix_runbooks_code', 'runbooks', ['code'])

    # 11. investigation_feedback
    op.create_table(
        'investigation_feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('investigation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('investigations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(length=128), server_default='alex.chen@acme.corp', nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comments', sa.Text(), nullable=True),
        sa.Column('was_root_cause_accurate', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_investigation_feedback_investigation_id', 'investigation_feedback', ['investigation_id'])


def downgrade() -> None:
    op.drop_table('investigation_feedback')
    op.drop_table('runbooks')
    op.drop_table('recommendations')
    op.drop_table('findings')
    op.drop_table('evidence')
    op.drop_table('investigations')
    op.drop_table('incident_events')
    op.drop_table('incidents')
    op.drop_table('services')
    op.drop_table('projects')
    op.drop_table('organizations')
