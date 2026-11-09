import React, { useEffect, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, SeverityBadge, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { IncidentItem, IncidentEvent, IncidentStatus, GroundedInvestigationResponse } from '../../types';

export const IncidentDetailsPage: React.FC = () => {
  const { incidentId = 'INC-8492' } = useParams<{ incidentId: string }>();
  const [incident, setIncident] = useState<IncidentItem | null>(null);
  const [timelineEvents, setTimelineEvents] = useState<IncidentEvent[]>([]);
  const [investigation, setInvestigation] = useState<GroundedInvestigationResponse | null>(null);
  const [loadingInv, setLoadingInv] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState<boolean>(false);
  const [transitionError, setTransitionError] = useState<string | null>(null);

  const loadTimeline = useCallback(async (id: string) => {
    try {
      const res = await apiClient.getIncidentTimeline(id);
      setTimelineEvents(res.data);
    } catch {
      // Non-blocking fallback
    }
  }, []);

  const loadInvestigation = useCallback(async (correlationGroupId: string) => {
    setLoadingInv(true);
    try {
      const res = await apiClient.getInvestigationByCorrelationGroup(correlationGroupId);
      setInvestigation(res.data);
    } catch {
      setInvestigation(null);
    } finally {
      setLoadingInv(false);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    apiClient
      .getIncidentById(incidentId)
      .then((res) => {
        if (!mounted) return;
        setIncident(res.data);
        setLoading(false);
        if (res.data) {
          loadTimeline(res.data.id);
          const corrId = res.data.correlationGroupId || res.data.correlation_group_id;
          if (corrId) {
            loadInvestigation(corrId);
          }
        }
      })
      .catch((err: unknown) => {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : 'Failed to fetch incident details');
        setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [incidentId, loadTimeline, loadInvestigation]);

  const handleStatusTransition = async (targetStatus: IncidentStatus) => {
    if (!incident) return;
    setTransitioning(true);
    setTransitionError(null);
    try {
      const res = await apiClient.updateIncidentStatus(incident.id, {
        status: targetStatus,
        comment: `Incident status transitioned to ${targetStatus} by responder.`,
      });
      setIncident(res.data);
      await loadTimeline(incident.id);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setTransitionError(e.message || `Failed to transition incident status to ${targetStatus}.`);
    } finally {
      setTransitioning(false);
    }
  };

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

  const corrId = incident.correlationGroupId || incident.correlation_group_id;

  // Derive valid action buttons according to lifecycle state machine
  const renderStatusActions = () => {
    if (incident.status === 'DETECTED') {
      return (
        <>
          <Button
            variant="secondary"
            icon="search"
            onClick={() => handleStatusTransition('INVESTIGATING')}
            disabled={transitioning}
          >
            Start Investigation
          </Button>
          <Button
            variant="primary"
            icon="done_all"
            onClick={() => handleStatusTransition('ACKNOWLEDGED')}
            disabled={transitioning}
          >
            Acknowledge
          </Button>
        </>
      );
    }
    if (incident.status === 'INVESTIGATING') {
      return (
        <>
          <Button
            variant="secondary"
            icon="done_all"
            onClick={() => handleStatusTransition('ACKNOWLEDGED')}
            disabled={transitioning}
          >
            Acknowledge
          </Button>
          <Button
            variant="secondary"
            icon="healing"
            onClick={() => handleStatusTransition('MITIGATED')}
            disabled={transitioning}
          >
            Mitigate
          </Button>
          <Button
            variant="primary"
            icon="task_alt"
            onClick={() => handleStatusTransition('RESOLVED')}
            disabled={transitioning}
          >
            Resolve Incident
          </Button>
        </>
      );
    }
    if (incident.status === 'ACKNOWLEDGED') {
      return (
        <>
          <Button
            variant="secondary"
            icon="search"
            onClick={() => handleStatusTransition('INVESTIGATING')}
            disabled={transitioning}
          >
            Investigate
          </Button>
          <Button
            variant="secondary"
            icon="healing"
            onClick={() => handleStatusTransition('MITIGATED')}
            disabled={transitioning}
          >
            Mitigate
          </Button>
          <Button
            variant="primary"
            icon="task_alt"
            onClick={() => handleStatusTransition('RESOLVED')}
            disabled={transitioning}
          >
            Resolve Incident
          </Button>
        </>
      );
    }
    if (incident.status === 'MITIGATED') {
      return (
        <>
          <Button
            variant="secondary"
            icon="search"
            onClick={() => handleStatusTransition('INVESTIGATING')}
            disabled={transitioning}
          >
            Resume Investigation
          </Button>
          <Button
            variant="primary"
            icon="task_alt"
            onClick={() => handleStatusTransition('RESOLVED')}
            disabled={transitioning}
          >
            Resolve Incident
          </Button>
        </>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-mono-badge text-mono-badge bg-surface-container-high text-on-surface font-semibold">
        <span className="material-symbols-outlined text-[16px] text-tertiary">task_alt</span>
        INCIDENT RESOLVED
      </span>
    );
  };

  return (
    <div className="w-full px-margin-desktop py-margin-desktop">
      <div className="flex flex-col w-full gap-space-lg">
        {/* Breadcrumb & Command Header */}
        <PageHeader
          category="Incident Command"
          categoryIcon="emergency_home"
          categoryBadge={
            <div className="flex items-center gap-1.5 flex-wrap">
              <Link to="/incidents" className="hover:text-primary transition-colors">
                Incidents
              </Link>
              <span className="text-outline-variant">/</span>
              <span className="font-mono-badge text-mono-badge bg-surface-container-high text-on-surface px-1.5 py-0.5 rounded">
                {incident.id}
              </span>
              {corrId ? (
                <span className="font-mono-badge text-[10px] px-1.5 py-0.5 rounded bg-tertiary-container/30 text-tertiary border border-tertiary/20 font-medium">
                  TELEMETRY LINKED
                </span>
              ) : (
                <span className="font-mono-badge text-[10px] px-1 py-0.5 rounded bg-surface-container text-outline font-medium">
                  DEMO SCENARIO
                </span>
              )}
            </div>
          }
          title={`${incident.id}: ${incident.title}`}
          titleBadge={
            <div className="flex items-center gap-2 flex-wrap">
              <SeverityBadge severity={incident.severity} animated={incident.severity === 'CRITICAL'} />
              <span
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded font-mono-badge text-mono-badge font-semibold ${
                  incident.status === 'DETECTED'
                    ? 'bg-error-container text-on-error-container'
                    : incident.status === 'RESOLVED'
                    ? 'bg-surface-container-high text-outline'
                    : 'bg-primary-fixed text-on-primary-fixed'
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    incident.status === 'DETECTED'
                      ? 'bg-error animate-ping'
                      : incident.status === 'RESOLVED'
                      ? 'bg-outline'
                      : 'bg-primary'
                  }`}
                />
                STATUS: {incident.status}
              </span>
            </div>
          }
          subtitle={`Active Duration: ${incident.activeDuration} • Commander: ${incident.commander.name} (${incident.commander.role})`}
          actions={<div className="flex items-center gap-2 flex-wrap">{renderStatusActions()}</div>}
        />

        {/* Transition Error Notice */}
        {transitionError && (
          <div className="p-3 rounded-lg bg-error-container/40 border border-error/30 text-on-error-container text-body-default font-body-default flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-error text-[18px]">warning</span>
              <span>{transitionError}</span>
            </div>
            <button
              type="button"
              onClick={() => setTransitionError(null)}
              className="text-outline hover:text-on-surface"
            >
              <span className="material-symbols-outlined text-[16px]">close</span>
            </button>
          </div>
        )}

        {/* Impacted Entities Strip */}
        <div className="flex items-center gap-2 flex-wrap p-space-sm rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30">
          <span className="font-caption-ui text-caption-ui text-outline uppercase tracking-wider font-semibold">
            Impacted Services:
          </span>
          {incident.affectedServices && incident.affectedServices.length > 0 ? (
            incident.affectedServices.map((serviceName) => (
              <span
                key={serviceName}
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container text-on-surface font-mono-caption text-mono-caption"
              >
                <span className="material-symbols-outlined text-[13px] text-error">dns</span>
                <span>{serviceName}</span>
              </span>
            ))
          ) : incident.impactedEntities && incident.impactedEntities.length > 0 ? (
            incident.impactedEntities.map((entity) => (
              <span
                key={entity.name}
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container text-on-surface font-mono-caption text-mono-caption"
              >
                <span className="material-symbols-outlined text-[13px] text-error">database</span>
                <span>{entity.name}</span>
                <span className="text-error font-semibold">{entity.metricSummary}</span>
              </span>
            ))
          ) : (
            <span className="text-outline font-caption-ui text-caption-ui">No services registered</span>
          )}
        </div>

        {/* Linked Correlation & AI Investigation Section */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-[22px]">auto_awesome</span>
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                Linked AI Investigation &amp; Root Cause Analysis
              </span>
            </div>
            {corrId && (
              <span className="font-mono-caption text-mono-caption px-2 py-0.5 rounded bg-surface-container text-on-surface-variant">
                Cluster ID: {corrId}
              </span>
            )}
          </div>

          {loadingInv ? (
            <div className="py-space-md flex justify-center">
              <LoadingSpinner message="Retrieving persisted correlation investigation..." />
            </div>
          ) : corrId && investigation ? (
            <div className="flex flex-col gap-space-sm p-space-md rounded-lg bg-surface-container-low/70 border border-outline-variant/20">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded font-mono-badge text-mono-badge font-semibold ${
                      investigation.status === 'COMPLETED'
                        ? 'bg-tertiary-container/40 text-tertiary'
                        : investigation.status === 'FAILED'
                        ? 'bg-error-container text-on-error-container'
                        : 'bg-primary-fixed text-on-primary-fixed'
                    }`}
                  >
                    STATUS: {investigation.status}
                  </span>
                  <span className="font-caption-ui text-caption-ui text-outline">
                    Model: {investigation.model_name || 'gemini-2.0-flash'} • Prompt v{investigation.prompt_version || '1.0'}
                  </span>
                </div>
                <Link to={`/ai-investigations?correlation_group_id=${corrId}`}>
                  <Button variant="surface" size="sm" icon="open_in_new">
                    View in AI Investigation Center
                  </Button>
                </Link>
              </div>

              {investigation.result || investigation.investigation_json ? (
                (() => {
                  const invResult = investigation.result || investigation.investigation_json;
                  return (
                    <>
                      <p className="font-body-default text-body-default text-on-surface mt-1 leading-relaxed">
                        {invResult?.incident_summary}
                      </p>
                      {invResult?.root_cause_analysis && (
                        <div className="mt-2 space-y-1">
                          <span className="font-caption-ui text-caption-ui uppercase text-outline font-semibold">
                            Primary Root Cause Explanation:
                          </span>
                          <div className="p-2 rounded bg-surface-container text-body-default flex items-start gap-2">
                            <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-primary-fixed text-on-primary-fixed shrink-0">
                              {invResult.root_cause_analysis.service_name}
                            </span>
                            <div className="flex flex-col">
                              <span className="font-semibold text-on-surface">
                                {invResult.root_cause_analysis.explanation}
                              </span>
                              {invResult.root_cause_analysis.contributing_factors && (
                                <span className="text-on-surface-variant text-caption-ui mt-0.5">
                                  Factors: {invResult.root_cause_analysis.contributing_factors.join('; ')}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </>
                  );
                })()
              ) : (
                <p className="font-body-default text-body-default text-on-surface-variant">
                  {investigation.error_message || 'Investigation record exists with no payload.'}
                </p>
              )}
            </div>
          ) : corrId ? (
            <div className="p-space-md rounded-lg bg-surface-container-low/50 border border-outline-variant/20 flex flex-col md:flex-row items-start md:items-center justify-between gap-space-sm">
              <div className="flex flex-col gap-1">
                <span className="font-body-medium text-body-medium font-semibold text-on-surface">
                  No AI investigation generated yet
                </span>
                <span className="font-caption-ui text-caption-ui text-on-surface-variant">
                  This incident is backed by live correlation cluster telemetry. You can generate an evidence-grounded investigation report using Gemini.
                </span>
              </div>
              <Link to={`/ai-investigations?correlation_group_id=${corrId}`}>
                <Button variant="surface" size="sm" icon="auto_awesome">
                  Generate in AI Center
                </Button>
              </Link>
            </div>
          ) : (
            <div className="p-space-md rounded-lg bg-surface-container-low/50 border border-outline-variant/20 flex flex-col md:flex-row items-start md:items-center justify-between gap-space-sm">
              <div className="flex flex-col gap-1">
                <span className="font-body-medium text-body-medium font-semibold text-on-surface">
                  Demonstration Incident Scenario
                </span>
                <span className="font-caption-ui text-caption-ui text-on-surface-variant">
                  This is a pre-seeded demonstration incident scenario with synthetic database connection pool telemetry.
                </span>
              </div>
              <Link to="/ai-investigations">
                <Button variant="surface" size="sm" icon="auto_awesome">
                  Open AI Investigation Center
                </Button>
              </Link>
            </div>
          )}
        </div>

        {/* Incident Event History / Timeline */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-secondary text-[20px]">history</span>
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                Incident Audit Timeline &amp; State Transitions
              </span>
            </div>
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-surface-container text-on-surface-variant">
              {timelineEvents.length} Events Logged
            </span>
          </div>

          {timelineEvents.length > 0 ? (
            <div className="relative pl-6 space-y-4 border-l-2 border-outline-variant/30 ml-2">
              {timelineEvents.map((ev, idx) => (
                <div key={ev.id || idx} className="relative group">
                  <span
                    className={`absolute -left-[31px] top-1 w-3.5 h-3.5 rounded-full border-2 border-surface-container-lowest ${
                      ev.type === 'human'
                        ? 'bg-tertiary'
                        : ev.type === 'action'
                        ? 'bg-primary'
                        : 'bg-error'
                    }`}
                  />
                  <div className="flex flex-col gap-1 p-3 rounded-lg bg-surface-container-low/60 border border-outline-variant/20">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span className="font-body-medium text-body-medium font-semibold text-on-surface">
                        {ev.title}
                      </span>
                      <span className="font-mono-caption text-mono-caption text-outline">
                        {ev.timestamp ? new Date(ev.timestamp).toLocaleString() : ev.relativeTime}
                      </span>
                    </div>
                    <p className="font-body-default text-body-default text-on-surface-variant leading-relaxed">
                      {ev.description}
                    </p>
                    <div className="flex items-center gap-2 mt-1 text-[11px] text-outline font-mono">
                      <span>Source: {ev.source}</span>
                      <span>•</span>
                      <span>Type: {ev.type}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center text-on-surface-variant font-caption-ui text-caption-ui">
              No audit events recorded yet for this incident.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
