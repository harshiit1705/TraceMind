import React, { useEffect, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, SeverityBadge, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import {
  IncidentItem,
  IncidentEvent,
  IncidentStatus,
  GroundedInvestigationResponse,
  CorrelationGroup,
  ApplicationLogItem,
  RemediationDetail,
} from '../../types';

export const IncidentDetailsPage: React.FC = () => {
  const { incidentId = 'INC-8492' } = useParams<{ incidentId: string }>();
  const [incident, setIncident] = useState<IncidentItem | null>(null);
  const [timelineEvents, setTimelineEvents] = useState<IncidentEvent[]>([]);
  const [investigation, setInvestigation] = useState<GroundedInvestigationResponse | null>(null);
  const [correlationGroup, setCorrelationGroup] = useState<CorrelationGroup | null>(null);
  const [incidentLogs, setIncidentLogs] = useState<ApplicationLogItem[]>([]);
  const [evidenceTab, setEvidenceTab] = useState<'summary' | 'logs' | 'traces'>('summary');
  const [loadingInv, setLoadingInv] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState<boolean>(false);
  const [transitionError, setTransitionError] = useState<string | null>(null);

  // Phase 4 Remediation Workflow State
  const [remediations, setRemediations] = useState<RemediationDetail[]>([]);
  const [loadingRemediations, setLoadingRemediations] = useState<boolean>(false);
  const [activeRemediationAction, setActiveRemediationAction] = useState<{
    id: string;
    type: 'approve' | 'reject' | 'execute';
  } | null>(null);
  const [actionInput, setActionInput] = useState<{
    operatorName: string;
    notesOrReason: string;
  }>({ operatorName: 'Alex Chen (Staff SRE)', notesOrReason: '' });
  const [remediationError, setRemediationError] = useState<string | null>(null);
  const [actionInProgress, setActionInProgress] = useState<boolean>(false);

  const loadTimeline = useCallback(async (id: string) => {
    try {
      const res = await apiClient.getIncidentTimeline(id);
      setTimelineEvents(res.data);
    } catch {
      // Non-blocking fallback
    }
  }, []);

  const loadRemediations = useCallback(async (incId: string) => {
    setLoadingRemediations(true);
    try {
      const res = await apiClient.getRemediations(incId);
      setRemediations(res.data || []);
    } catch {
      // Non-blocking fallback
    } finally {
      setLoadingRemediations(false);
    }
  }, []);

  const loadInvestigation = useCallback(async (correlationGroupId: string, incId: string) => {
    setLoadingInv(true);
    try {
      const [invRes, corrRes, logsRes] = await Promise.all([
        apiClient.getInvestigationByCorrelationGroup(correlationGroupId),
        apiClient.getCorrelationById(correlationGroupId).catch(() => null),
        apiClient.getIncidentLogs(incId, 20).catch(() => null),
      ]);
      setInvestigation(invRes.data);
      setCorrelationGroup(corrRes ? corrRes.data : null);
      setIncidentLogs(logsRes ? logsRes.data : []);
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
          loadRemediations(res.data.id);
          const corrId = res.data.correlationGroupId || res.data.correlation_group_id;
          if (corrId) {
            loadInvestigation(corrId, res.data.id);
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
  }, [incidentId, loadTimeline, loadInvestigation, loadRemediations]);

  const handleApproveRemediation = async (remId: string) => {
    setActionInProgress(true);
    setRemediationError(null);
    try {
      const res = await apiClient.approveRemediation(remId, {
        approver_name: actionInput.operatorName || 'Alex Chen (Staff SRE)',
        approval_notes: actionInput.notesOrReason || 'Verified safe for production execution.',
      });
      setRemediations((prev) => prev.map((r) => (r.id === remId ? res.data : r)));
      setActiveRemediationAction(null);
      if (incident) {
        await loadTimeline(incident.id);
      }
    } catch (err: unknown) {
      const e = err as { message?: string };
      setRemediationError(e.message || 'Failed to approve remediation.');
    } finally {
      setActionInProgress(false);
    }
  };

  const handleRejectRemediation = async (remId: string) => {
    if (!actionInput.notesOrReason.trim()) {
      setRemediationError('A rejection reason is mandatory when rejecting a remediation.');
      return;
    }
    setActionInProgress(true);
    setRemediationError(null);
    try {
      const res = await apiClient.rejectRemediation(remId, {
        rejector_name: actionInput.operatorName || 'Alex Chen (Staff SRE)',
        rejection_reason: actionInput.notesOrReason,
      });
      setRemediations((prev) => prev.map((r) => (r.id === remId ? res.data : r)));
      setActiveRemediationAction(null);
      if (incident) {
        await loadTimeline(incident.id);
      }
    } catch (err: unknown) {
      const e = err as { message?: string };
      setRemediationError(e.message || 'Failed to reject remediation.');
    } finally {
      setActionInProgress(false);
    }
  };

  const handleExecuteRemediation = async (remId: string) => {
    setActionInProgress(true);
    setRemediationError(null);
    try {
      const res = await apiClient.executeRemediation(remId, {
        executor_name: actionInput.operatorName || 'Alex Chen (Staff SRE)',
      });
      setRemediations((prev) => prev.map((r) => (r.id === remId ? res.data : r)));
      setActiveRemediationAction(null);
      if (incident) {
        await loadTimeline(incident.id);
      }
    } catch (err: unknown) {
      const e = err as { message?: string };
      setRemediationError(e.message || 'Failed to execute remediation.');
    } finally {
      setActionInProgress(false);
    }
  };

  const handleCancelRemediation = async (remId: string) => {
    setActionInProgress(true);
    setRemediationError(null);
    try {
      const res = await apiClient.cancelRemediation(remId, {
        cancelled_by: actionInput.operatorName || 'Alex Chen (Staff SRE)',
        cancellation_reason: 'Cancelled by operator.',
      });
      setRemediations((prev) => prev.map((r) => (r.id === remId ? res.data : r)));
      if (incident) {
        await loadTimeline(incident.id);
      }
    } catch (err: unknown) {
      const e = err as { message?: string };
      setRemediationError(e.message || 'Failed to cancel remediation.');
    } finally {
      setActionInProgress(false);
    }
  };

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

        {/* Multi-Signal Deterministic Root Cause & Evidence Card */}
        {corrId && correlationGroup && correlationGroup.ranked_candidates.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[22px]">hub</span>
                <span className="font-title-md text-title-md text-on-surface font-semibold">
                  Deterministic Multi-Signal Root Cause &amp; Evidence
                </span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {(['summary', 'logs', 'traces'] as const).map((tabKey) => (
                  <button
                    key={tabKey}
                    type="button"
                    onClick={() => setEvidenceTab(tabKey)}
                    className={`px-2.5 py-1 rounded-lg font-mono-badge text-mono-badge uppercase font-semibold transition-colors ${
                      evidenceTab === tabKey
                        ? 'bg-primary text-on-primary'
                        : 'bg-surface-container text-on-surface-variant hover:bg-surface-container-high'
                    }`}
                  >
                    {tabKey === 'summary' ? 'Root Cause & Signals' : tabKey === 'logs' ? `Logs (${incidentLogs.length})` : `Traces (${correlationGroup.evidence_summary?.trace_bottlenecks.length || 0})`}
                  </button>
                ))}
                <Link to="/dependencies">
                  <Button variant="surface" size="sm" icon="device_hub">Dependency Map</Button>
                </Link>
              </div>
            </div>

            {evidenceTab === 'summary' && (() => {
              const topCand = correlationGroup.ranked_candidates[0];
              const evSum = correlationGroup.evidence_summary;
              return (
                <div className="flex flex-col gap-space-sm">
                  <div className="p-space-md rounded-lg bg-primary-fixed/15 border border-primary/25 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-caption-ui text-caption-ui uppercase text-outline font-semibold">
                        #1 Probable Root Cause Service
                      </span>
                      <span className="font-title-sm font-semibold text-on-surface">
                        {topCand.service_name} ({topCand.service_slug})
                      </span>
                      {(topCand.primary_suspected_operation || correlationGroup.primary_suspected_operation) && (
                        <span className="font-mono-caption text-mono-caption text-primary">
                          Suspected Operation: {topCand.primary_suspected_operation || correlationGroup.primary_suspected_operation}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-surface-container text-on-surface font-semibold">
                        Score: {(topCand.score * 100).toFixed(1)}%
                      </span>
                      <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-secondary-container text-on-secondary-fixed font-semibold">
                        {topCand.confidence} CONFIDENCE
                      </span>
                    </div>
                  </div>

                  {evSum && (
                    <div className="flex items-center gap-2 flex-wrap text-xs">
                      <span className="font-mono-caption text-outline uppercase font-semibold">Signals:</span>
                      {evSum.coverage.observed_signals.map((sig) => (
                        <span key={sig} className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200 font-mono-badge">
                          {sig}
                        </span>
                      ))}
                      {evSum.coverage.missing_signals.map((sig) => (
                        <span key={sig} className="px-2 py-0.5 rounded bg-surface-container text-outline font-mono-badge">
                          missing: {sig}
                        </span>
                      ))}
                    </div>
                  )}

                  {topCand.supporting_evidence.length > 0 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {topCand.supporting_evidence.slice(0, 4).map((ev, i) => (
                        <div key={i} className="p-2 rounded bg-surface-container-low border border-outline-variant/20 text-xs text-on-surface-variant">
                          {ev}
                        </div>
                      ))}
                    </div>
                  )}

                  {topCand.contradictory_evidence && topCand.contradictory_evidence.length > 0 && (
                    <div className="p-2.5 rounded bg-error-container/30 border border-error/25 text-xs text-on-error-container">
                      <strong>Contradictory Evidence:</strong> {topCand.contradictory_evidence.join(' • ')}
                    </div>
                  )}
                </div>
              );
            })()}

            {evidenceTab === 'logs' && (
              <div className="flex flex-col gap-2">
                {incidentLogs.length > 0 ? (
                  incidentLogs.slice(0, 10).map((lg) => (
                    <div key={lg.id} className="p-2.5 rounded-lg bg-surface-container-low border border-outline-variant/20 flex flex-wrap items-center justify-between gap-2 text-xs">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className={`px-1.5 py-0.5 rounded font-mono-badge font-semibold ${lg.level === 'ERROR' || lg.level === 'CRITICAL' ? 'bg-error-container text-on-error-container' : 'bg-surface-container text-on-surface-variant'}`}>
                          {lg.level}
                        </span>
                        <span className="font-mono-caption font-semibold text-on-surface">{lg.service_name || lg.service_slug}</span>
                        <span className="text-on-surface-variant truncate">{lg.message}</span>
                      </div>
                      {lg.trace_id && (
                        <Link to={`/logs?trace_id=${encodeURIComponent(lg.trace_id)}`} className="font-mono-caption text-primary hover:underline shrink-0">
                          Trace {lg.trace_id.slice(0, 10)}
                        </Link>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="text-xs text-outline py-2">No persisted logs recorded in incident window.</div>
                )}
              </div>
            )}

            {evidenceTab === 'traces' && (
              <div className="flex flex-col gap-2">
                {(correlationGroup.evidence_summary?.trace_bottlenecks || []).length > 0 ? (
                  (correlationGroup.evidence_summary?.trace_bottlenecks || []).slice(0, 10).map((tb) => (
                    <div key={`${tb.trace_id}-${tb.span_id}`} className="p-2.5 rounded-lg bg-surface-container-low border border-outline-variant/20 flex flex-wrap items-center justify-between gap-2 text-xs">
                      <div className="flex items-center gap-2">
                        <span className={`px-1.5 py-0.5 rounded font-mono-badge font-semibold ${tb.is_origin_error ? 'bg-error-container text-on-error-container' : 'bg-primary-fixed text-on-primary-fixed'}`}>
                          {tb.is_origin_error ? 'ORIGIN ERROR' : 'BOTTLENECK'}
                        </span>
                        <span className="font-semibold text-on-surface">{tb.service_name}</span>
                        <span className="font-mono-caption text-on-surface-variant">{tb.operation_name}</span>
                      </div>
                      <div className="flex items-center gap-3 font-mono-caption">
                        <span>self-time: {tb.self_time_ms.toFixed(1)}ms ({(tb.self_time_share * 100).toFixed(0)}%)</span>
                        <Link to={`/traces?trace_id=${encodeURIComponent(tb.trace_id)}`} className="text-primary hover:underline">
                          Open Waterfall
                        </Link>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-xs text-outline py-2">No persisted bottleneck trace spans in incident window.</div>
                )}
              </div>
            )}
          </div>
        )}

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
                      <div className="flex items-center gap-2 flex-wrap">
                        {invResult?.conclusion_status && (
                          <span className="font-mono-badge text-[10px] px-2 py-0.5 rounded bg-surface-container text-on-surface font-semibold uppercase">
                            {invResult.conclusion_status}
                          </span>
                        )}
                        {invResult?.confidence_level && (
                          <span className="font-mono-badge text-[10px] px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed font-semibold uppercase">
                            AI CONFIDENCE: {invResult.confidence_level}
                          </span>
                        )}
                        {investigation.evidence_stale && (
                          <span className="font-mono-badge text-[10px] px-2 py-0.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200 font-semibold uppercase">
                            EVIDENCE UPDATED
                          </span>
                        )}
                      </div>
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

        {/* Phase 4: Remediation & Human Recovery Workflow */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-[22px]">build_circle</span>
              <div className="flex flex-col">
                <span className="font-title-md text-title-md text-on-surface font-semibold">
                  Remediation &amp; Human Recovery Workflow
                </span>
                <span className="font-caption-ui text-caption-ui text-outline">
                  Strict allowlisted remediation actions • Autonomous AI execution prohibited
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-1 rounded bg-error-container text-on-error-container font-mono-badge text-mono-badge font-semibold tracking-wide uppercase">
                HUMAN APPROVAL REQUIRED
              </span>
              <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-surface-container text-on-surface-variant">
                {remediations.length} Action{remediations.length === 1 ? '' : 's'}
              </span>
            </div>
          </div>

          {remediationError && (
            <div className="p-3 rounded-lg bg-error-container/80 text-on-error-container flex items-center justify-between gap-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px]">error</span>
                <span>{remediationError}</span>
              </div>
              <button
                type="button"
                onClick={() => setRemediationError(null)}
                className="text-on-error-container hover:opacity-70 font-semibold"
              >
                Dismiss
              </button>
            </div>
          )}

          {loadingRemediations ? (
            <div className="py-space-md flex justify-center">
              <LoadingSpinner message="Loading incident remediations..." />
            </div>
          ) : remediations.length === 0 ? (
            <div className="p-space-md rounded-lg bg-surface-container-low/50 border border-outline-variant/20 flex flex-col md:flex-row items-start md:items-center justify-between gap-space-sm">
              <div className="flex flex-col gap-1">
                <span className="font-body-medium text-body-medium font-semibold text-on-surface">
                  No remediation proposed yet
                </span>
                <span className="font-caption-ui text-caption-ui text-on-surface-variant">
                  You can propose an allowlisted remediation action (such as fault reset or pod restart) to resolve this incident.
                </span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                icon="add_task"
                onClick={async () => {
                  setActionInProgress(true);
                  try {
                    const res = await apiClient.proposeRemediation(incident.id, {
                      title: 'Reset Payment Service Faults and Connection Locks',
                      target_service: 'payment-service',
                      description: 'Reset faults and clear deadlocks on payment-service to restore throughput.',
                      action_name: 'RESET_SERVICE_FAULTS',
                      risk_level: 'LOW',
                      preconditions: ['Payment error rate > 5% or latency > 1000ms'],
                      rollback_procedure: 'Re-route traffic or restart container if lock persists',
                      expected_result: 'Payment service error rate drops to 0% and latency normalizes',
                      verification_steps: ['Check GET /health on payment-service'],
                      proposer_name: 'Alex Chen (Staff SRE)',
                    });
                    setRemediations((prev) => [...prev, res.data]);
                    await loadTimeline(incident.id);
                  } catch (err: unknown) {
                    const e = err as { message?: string };
                    setRemediationError(e.message || 'Failed to propose remediation');
                  } finally {
                    setActionInProgress(false);
                  }
                }}
                disabled={actionInProgress}
              >
                Propose Fault Reset Action
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-space-md">
              {remediations.map((rem) => {
                const isActionActive = activeRemediationAction?.id === rem.id;
                const actionType = activeRemediationAction?.type;

                const statusBadge = () => {
                  switch (rem.status) {
                    case 'PROPOSED':
                      return (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded font-mono-badge text-mono-badge font-semibold bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200 border border-amber-300 dark:border-amber-800">
                          <span className="material-symbols-outlined text-[14px]">pending</span>
                          PROPOSED — AWAITING SRE APPROVAL
                        </span>
                      );
                    case 'APPROVED':
                      return (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded font-mono-badge text-mono-badge font-semibold bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200 border border-sky-300 dark:border-sky-800">
                          <span className="material-symbols-outlined text-[14px]">verified</span>
                          APPROVED — READY FOR EXECUTION
                        </span>
                      );
                    case 'EXECUTING':
                      return (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded font-mono-badge text-mono-badge font-semibold bg-purple-100 text-purple-900 dark:bg-purple-950 dark:text-purple-200 animate-pulse">
                          <span className="material-symbols-outlined text-[14px] animate-spin">autorenew</span>
                          EXECUTING ALLOWLISTED ACTION
                        </span>
                      );
                    case 'EXECUTED':
                      return (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded font-mono-badge text-mono-badge font-semibold bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border border-emerald-300 dark:border-emerald-800">
                          <span className="material-symbols-outlined text-[14px]">check_circle</span>
                          EXECUTED &amp; CONFIRMED
                        </span>
                      );
                    case 'REJECTED':
                      return (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded font-mono-badge text-mono-badge font-semibold bg-rose-100 text-rose-900 dark:bg-rose-950 dark:text-rose-200 border border-rose-300 dark:border-rose-800">
                          <span className="material-symbols-outlined text-[14px]">cancel</span>
                          REJECTED BY OPERATOR
                        </span>
                      );
                    case 'CANCELLED':
                      return (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded font-mono-badge text-mono-badge font-semibold bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200">
                          <span className="material-symbols-outlined text-[14px]">block</span>
                          CANCELLED
                        </span>
                      );
                    default:
                      return (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded font-mono-badge text-mono-badge font-semibold bg-error-container text-on-error-container">
                          <span className="material-symbols-outlined text-[14px]">error</span>
                          {rem.status}
                        </span>
                      );
                  }
                };

                return (
                  <div
                    key={rem.id}
                    className="p-space-md rounded-lg bg-surface-container-low border border-outline-variant/30 flex flex-col gap-3 transition-all"
                  >
                    {/* Header: Title + Status + Action Name */}
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-title-sm text-title-sm font-semibold text-on-surface">
                          {rem.title}
                        </span>
                        <span className="px-2 py-0.5 rounded bg-surface-container-high text-primary font-mono-badge text-[11px] font-semibold">
                          {rem.action_name}
                        </span>
                        <span className="px-2 py-0.5 rounded bg-surface-container text-secondary font-mono-badge text-[11px]">
                          Target: {rem.target_service}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2 py-0.5 rounded font-mono-badge text-[10px] font-semibold uppercase ${
                            rem.risk_level === 'HIGH'
                              ? 'bg-error-container text-on-error-container'
                              : rem.risk_level === 'MEDIUM'
                              ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                              : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                          }`}
                        >
                          {rem.risk_level} RISK
                        </span>
                        {statusBadge()}
                      </div>
                    </div>

                    {/* Description */}
                    <p className="text-on-surface font-body-default text-body-default leading-relaxed">
                      {rem.description}
                    </p>

                    {/* Preconditions, Expected Results, Verification */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs pt-1">
                      {rem.preconditions && rem.preconditions.length > 0 && (
                        <div className="p-2 rounded bg-surface-container-lowest/60 border border-outline-variant/20 flex flex-col gap-1">
                          <span className="font-mono-badge text-[10px] uppercase font-semibold text-outline">
                            Preconditions:
                          </span>
                          {rem.preconditions.map((p, idx) => (
                            <div key={idx} className="flex items-center gap-1.5 text-on-surface-variant">
                              <span className="material-symbols-outlined text-[13px] text-primary">check</span>
                              <span>{p}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {rem.expected_result && (
                        <div className="p-2 rounded bg-surface-container-lowest/60 border border-outline-variant/20 flex flex-col gap-1">
                          <span className="font-mono-badge text-[10px] uppercase font-semibold text-outline">
                            Expected Outcome:
                          </span>
                          <span className="text-on-surface-variant">{rem.expected_result}</span>
                        </div>
                      )}

                      {rem.verification_steps && rem.verification_steps.length > 0 && (
                        <div className="p-2 rounded bg-surface-container-lowest/60 border border-outline-variant/20 flex flex-col gap-1">
                          <span className="font-mono-badge text-[10px] uppercase font-semibold text-outline">
                            Verification Steps:
                          </span>
                          <span className="text-on-surface-variant">
                            {rem.verification_steps.join(' • ')}
                          </span>
                        </div>
                      )}

                      {rem.rollback_procedure && (
                        <div className="p-2 rounded bg-surface-container-lowest/60 border border-outline-variant/20 flex flex-col gap-1">
                          <span className="font-mono-badge text-[10px] uppercase font-semibold text-outline">
                            Rollback Procedure:
                          </span>
                          <span className="text-on-surface-variant">{rem.rollback_procedure}</span>
                        </div>
                      )}
                    </div>

                    {/* Approval Audit Banner */}
                    {rem.approved_by && (
                      <div className="p-2.5 rounded bg-sky-50 dark:bg-sky-950/40 border border-sky-200 dark:border-sky-800 text-xs flex flex-col gap-1">
                        <div className="flex items-center justify-between text-sky-900 dark:text-sky-200 font-semibold font-mono-caption">
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[15px]">verified_user</span>
                            Approved by: {rem.approved_by}
                          </span>
                          <span>{rem.approved_at ? new Date(rem.approved_at).toLocaleString() : ''}</span>
                        </div>
                        {rem.approval_notes && (
                          <span className="text-sky-800 dark:text-sky-300">
                            Notes: {rem.approval_notes}
                          </span>
                        )}
                      </div>
                    )}

                    {/* Rejection Audit Banner */}
                    {rem.rejected_by && (
                      <div className="p-2.5 rounded bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-xs flex flex-col gap-1">
                        <div className="flex items-center justify-between text-rose-900 dark:text-rose-200 font-semibold font-mono-caption">
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[15px]">cancel</span>
                            Rejected by: {rem.rejected_by}
                          </span>
                          <span>{rem.rejected_at ? new Date(rem.rejected_at).toLocaleString() : ''}</span>
                        </div>
                        <span className="text-rose-800 dark:text-rose-300">
                          Reason: {rem.rejection_reason}
                        </span>
                      </div>
                    )}

                    {/* Execution Audit & Results Banner */}
                    {rem.executed_by && (
                      <div className="p-2.5 rounded bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-xs flex flex-col gap-1.5">
                        <div className="flex items-center justify-between text-emerald-900 dark:text-emerald-200 font-semibold font-mono-caption flex-wrap gap-2">
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[15px]">done_all</span>
                            Executed by: {rem.executed_by}
                          </span>
                          <div className="flex items-center gap-2">
                            <span className="px-1.5 py-0.5 rounded bg-emerald-200 dark:bg-emerald-800 text-emerald-950 dark:text-emerald-100 font-mono text-[10px] font-bold">
                              MODE: {rem.execution_mode || 'REAL'}
                            </span>
                            <span>{rem.executed_at ? new Date(rem.executed_at).toLocaleString() : ''}</span>
                          </div>
                        </div>
                        {rem.execution_result_json && (
                          <div className="p-2 rounded bg-surface-container-lowest font-mono text-[11px] text-on-surface-variant overflow-x-auto">
                            <span>Status: {rem.execution_result_json.status || 'OK'}</span>
                            {' • '}
                            <span>Target: {rem.execution_result_json.target_service}</span>
                            {' • '}
                            <span>Verified: {rem.execution_result_json.verified ? 'YES' : 'NO'}</span>
                            {rem.execution_result_json.response_data && (
                              <div className="mt-1 text-[10px] text-outline">
                                Response: {JSON.stringify(rem.execution_result_json.response_data)}
                              </div>
                            )}
                          </div>
                        )}
                        {rem.execution_error && (
                          <div className="text-error font-mono text-[11px]">
                            Execution Error: {rem.execution_error}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Inline Form Drawer for Approval / Rejection / Execution */}
                    {isActionActive && (
                      <div className="p-3 rounded-lg bg-surface-container-high/80 border border-primary/30 flex flex-col gap-2.5 animate-fadeIn">
                        <div className="flex items-center justify-between">
                          <span className="font-title-sm text-title-sm font-semibold text-primary">
                            {actionType === 'approve'
                              ? 'Human SRE Approval Confirmation'
                              : actionType === 'reject'
                              ? 'Human SRE Rejection'
                              : 'Execute Allowlisted Remediation Action'}
                          </span>
                          <button
                            type="button"
                            onClick={() => setActiveRemediationAction(null)}
                            className="text-on-surface-variant hover:text-on-surface text-xs"
                          >
                            Cancel
                          </button>
                        </div>

                        <div className="flex flex-col gap-2">
                          <div className="flex flex-col gap-1">
                            <label className="text-[11px] font-mono-badge uppercase text-outline">
                              Operator Name / Identity:
                            </label>
                            <input
                              type="text"
                              value={actionInput.operatorName}
                              onChange={(e) =>
                                setActionInput((prev) => ({ ...prev, operatorName: e.target.value }))
                              }
                              className="px-2.5 py-1.5 rounded bg-surface-container text-xs text-on-surface border border-outline-variant/40 focus:outline-none focus:border-primary"
                              placeholder="e.g. Alex Chen (Staff SRE)"
                            />
                          </div>

                          {actionType !== 'execute' && (
                            <div className="flex flex-col gap-1">
                              <label className="text-[11px] font-mono-badge uppercase text-outline">
                                {actionType === 'approve' ? 'Approval Notes (Optional):' : 'Rejection Reason (Required):'}
                              </label>
                              <textarea
                                value={actionInput.notesOrReason}
                                onChange={(e) =>
                                  setActionInput((prev) => ({ ...prev, notesOrReason: e.target.value }))
                                }
                                rows={2}
                                className="px-2.5 py-1.5 rounded bg-surface-container text-xs text-on-surface border border-outline-variant/40 focus:outline-none focus:border-primary"
                                placeholder={
                                  actionType === 'approve'
                                    ? 'e.g. Verified lock contention in traces; safe to reset faults.'
                                    : 'e.g. Action would exhaust database pool during peak traffic.'
                                }
                              />
                            </div>
                          )}

                          <div className="flex items-center justify-end gap-2 pt-1">
                            <Button
                              variant="surface"
                              size="sm"
                              onClick={() => setActiveRemediationAction(null)}
                              disabled={actionInProgress}
                            >
                              Cancel
                            </Button>
                            {actionType === 'approve' && (
                              <Button
                                variant="primary"
                                size="sm"
                                icon="verified"
                                onClick={() => handleApproveRemediation(rem.id)}
                                disabled={actionInProgress}
                              >
                                {actionInProgress ? 'Approving...' : 'Confirm Approval'}
                              </Button>
                            )}
                            {actionType === 'reject' && (
                              <Button
                                variant="secondary"
                                size="sm"
                                icon="cancel"
                                onClick={() => handleRejectRemediation(rem.id)}
                                disabled={actionInProgress}
                              >
                                {actionInProgress ? 'Rejecting...' : 'Confirm Rejection'}
                              </Button>
                            )}
                            {actionType === 'execute' && (
                              <Button
                                variant="primary"
                                size="sm"
                                icon="play_arrow"
                                onClick={() => handleExecuteRemediation(rem.id)}
                                disabled={actionInProgress}
                              >
                                {actionInProgress ? 'Executing...' : 'Run Action Now'}
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Bottom Action Bar */}
                    {!isActionActive && (
                      <div className="flex items-center justify-between pt-2 border-t border-outline-variant/20 flex-wrap gap-2">
                        <div className="flex items-center gap-1.5 text-secondary text-xs">
                          <span className="material-symbols-outlined text-[16px] text-primary">lock</span>
                          <span className="font-mono-badge text-[11px]">
                            {rem.status === 'PROPOSED'
                              ? 'Autonomous execution prohibited • SRE authorization required'
                              : rem.status === 'APPROVED'
                              ? 'Human approved • Ready to execute safely'
                              : rem.status === 'EXECUTED'
                              ? 'Remediation completed successfully'
                              : 'Workflow finished'}
                          </span>
                        </div>

                        <div className="flex items-center gap-2">
                          {rem.status === 'PROPOSED' && (
                            <>
                              <Button
                                variant="secondary"
                                size="sm"
                                icon="cancel"
                                onClick={() => {
                                  setActionInput({
                                    operatorName: incident.commander?.name || 'Alex Chen (Staff SRE)',
                                    notesOrReason: '',
                                  });
                                  setActiveRemediationAction({ id: rem.id, type: 'reject' });
                                }}
                                disabled={actionInProgress}
                              >
                                Reject
                              </Button>
                              <Button
                                variant="primary"
                                size="sm"
                                icon="verified"
                                onClick={() => {
                                  setActionInput({
                                    operatorName: incident.commander?.name || 'Alex Chen (Staff SRE)',
                                    notesOrReason: 'Production lock contention verified. Approved for execution.',
                                  });
                                  setActiveRemediationAction({ id: rem.id, type: 'approve' });
                                }}
                                disabled={actionInProgress}
                              >
                                Approve Action
                              </Button>
                            </>
                          )}

                          {rem.status === 'APPROVED' && (
                            <>
                              <Button
                                variant="surface"
                                size="sm"
                                icon="block"
                                onClick={() => handleCancelRemediation(rem.id)}
                                disabled={actionInProgress}
                              >
                                Cancel
                              </Button>
                              <Button
                                variant="primary"
                                size="sm"
                                icon="play_arrow"
                                onClick={() => {
                                  setActionInput({
                                    operatorName: incident.commander?.name || 'Alex Chen (Staff SRE)',
                                    notesOrReason: '',
                                  });
                                  setActiveRemediationAction({ id: rem.id, type: 'execute' });
                                }}
                                disabled={actionInProgress}
                              >
                                Execute Remediation
                              </Button>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
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
