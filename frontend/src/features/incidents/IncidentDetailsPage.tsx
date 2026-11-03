import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, SeverityBadge, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { IncidentItem } from '../../types';

export const IncidentDetailsPage: React.FC = () => {
  const { incidentId = 'INC-8492' } = useParams<{ incidentId: string }>();
  const [incident, setIncident] = useState<IncidentItem | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiClient.getIncidentById(incidentId)
      .then((res) => {
        if (mounted) {
          setIncident(res.data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to fetch incident details');
          setLoading(false);
        }
      });
    return () => { mounted = false; };
  }, [incidentId]);

  if (loading) {
    return <LoadingSpinner message="Loading incident telemetry stream..." />;
  }

  if (error || !incident) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <ErrorState
          title="Incident Not Found"
          message={error || `Could not find telemetry for incident ID: ${incidentId}`}
          details={{ endpoint: `/api/v1/incidents/${incidentId}` }}
        />
      </div>
    );
  }

  return (
    <div className="w-full px-margin-desktop py-margin-desktop">
      <div className="flex flex-col w-full gap-space-lg">
        {/* Breadcrumb & Command Header */}
        <PageHeader
          category="Incident Command"
          categoryIcon="emergency_home"
          categoryBadge={
            <div className="flex items-center gap-1.5">
              <Link to="/incidents" className="hover:text-primary transition-colors">
                Incidents
              </Link>
              <span className="text-outline-variant">/</span>
              <span className="font-mono-badge text-mono-badge bg-surface-container-high text-on-surface px-1.5 py-0.5 rounded">
                {incident.id}
              </span>
            </div>
          }
          title={`${incident.id}: ${incident.title}`}
          titleBadge={
            <div className="flex items-center gap-2 flex-wrap">
              <SeverityBadge severity={incident.severity} animated={incident.severity === 'CRITICAL'} />
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed font-mono-badge text-mono-badge font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                STATUS: {incident.status}
              </span>
            </div>
          }
          subtitle={`Active Duration: ${incident.activeDuration} • Commander: ${incident.commander.name} (${incident.commander.role})`}
          actions={
            <>
              <Button variant="secondary" icon="done_all">Acknowledge</Button>
              <Button variant="secondary" icon="menu_book" iconRight="open_in_new">Runbook</Button>
              <Button variant="secondary" icon="groups">War Room</Button>
              <Button variant="primary" icon="task_alt">Resolve Incident</Button>
            </>
          }
        />

        {/* Impacted Entities Strip */}
        <div className="flex items-center gap-2 flex-wrap p-space-sm rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30">
          <span className="font-caption-ui text-caption-ui text-outline uppercase tracking-wider font-semibold">
            Impacted Entities:
          </span>
          {incident.impactedEntities.map((entity) => (
            <span
              key={entity.name}
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container text-on-surface font-mono-caption text-mono-caption"
            >
              <span className="material-symbols-outlined text-[13px] text-error">database</span>
              <span>{entity.name}</span>
              <span className="text-error font-semibold">{entity.metricSummary}</span>
            </span>
          ))}
        </div>

        {/* Phase 2.1 Workspace Placeholder Notice */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-sm">
          <div className="flex items-center justify-between">
            <span className="font-title-md text-title-md text-on-surface font-semibold">
              Incident Investigation Command Scaffolding
            </span>
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed">
              LIVE TELEMETRY SYNCED
            </span>
          </div>
          <p className="font-body-default text-body-default text-on-surface-variant leading-relaxed">
            The twin Golden Signals charts, root cause synthesis panel, dry-run SQL remediation script runner, and 7-stage event stream audit timeline are scoped for Phase 2.3.
          </p>
          <div className="pt-space-xs flex items-center gap-space-xs">
            <Link to="/ai-investigations">
              <Button variant="surface" size="sm" icon="auto_awesome">
                Open AI Investigation Center
              </Button>
            </Link>
            <Link to="/traces">
              <Button variant="surface" size="sm" icon="insights">
                Correlate Distributed Traces
              </Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
};

