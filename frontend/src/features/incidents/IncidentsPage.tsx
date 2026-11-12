import React, { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { IncidentItem, IncidentsKpiStats } from '../../types';

export const IncidentsPage: React.FC = () => {
  const navigate = useNavigate();

  const [incidents, setIncidents] = useState<IncidentItem[]>([]);
  const [kpiStats, setKpiStats] = useState<IncidentsKpiStats | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<{ message: string; details?: Record<string, unknown> } | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'detected' | 'investigating' | 'mitigated' | 'resolved'>('all');
  const [severityFilter, setSeverityFilter] = useState<'all' | 'critical' | 'high' | 'medium' | 'low'>('all');

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getIncidents(),
      apiClient.getIncidentsKpiStats(),
    ])
      .then(([incidentsRes, statsRes]) => {
        if (!mounted) return;
        setIncidents(incidentsRes.data);
        setKpiStats(statsRes.data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!mounted) return;
        const e = err as { message?: string; details?: Record<string, unknown> };
        setError({
          message: e.message || 'Failed to load incidents list',
          details: e.details,
        });
        setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  // Filter incidents based on search query, status tab, and severity badge
  const filteredIncidents = useMemo(() => {
    return incidents.filter((incident) => {
      const q = searchQuery.toLowerCase();
      const matchesSearch =
        incident.id.toLowerCase().includes(q) ||
        incident.title.toLowerCase().includes(q) ||
        incident.commander.name.toLowerCase().includes(q) ||
        incident.affectedServices.some((s) => s.toLowerCase().includes(q));

      if (!matchesSearch) return false;

      if (statusFilter !== 'all') {
        if (statusFilter === 'active') {
          if (incident.status === 'RESOLVED') return false;
        } else if (incident.status.toLowerCase() !== statusFilter) {
          return false;
        }
      }

      if (severityFilter !== 'all') {
        if (incident.severity.toLowerCase() !== severityFilter) {
          return false;
        }
      }

      return true;
    });
  }, [incidents, searchQuery, statusFilter, severityFilter]);

  const criticalCount = incidents.filter((i) => i.severity === 'CRITICAL').length;
  const highCount = incidents.filter((i) => i.severity === 'HIGH').length;
  const mediumCount = incidents.filter((i) => i.severity === 'MEDIUM').length;
  const lowCount = incidents.filter((i) => i.severity === 'LOW').length;

  const computedKpiStats = useMemo(() => {
    const active = incidents.filter((i) => i.status !== 'RESOLVED').length;
    const critical = incidents.filter((i) => i.severity === 'CRITICAL' && i.status !== 'RESOLVED').length;
    const acked = incidents.filter((i) => i.status === 'ACKNOWLEDGED').length;
    const resolved = incidents.filter((i) => i.status === 'RESOLVED').length;
    return {
      activeCount: active,
      criticalImpactCount: critical,
      acknowledgedCount: acked,
      resolved24hCount: resolved,
      mttdFormatted: kpiStats?.mttdFormatted ?? '1m 30s',
      mttrFormatted: kpiStats?.mttrFormatted ?? '14m 20s',
    };
  }, [incidents, kpiStats]);

  if (loading && incidents.length === 0) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <LoadingSpinner message="Loading live incident command stream and active alerts..." fullScreen />
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <ErrorState
          title="Incident Command Stream Error"
          message={error.message}
          details={error.details}
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  return (
    <div className="w-full px-margin-desktop py-margin-desktop space-y-space-xl">
      {/* Page Header & Action Canvas */}
      <PageHeader
        category="Incident Command"
        categoryIcon="emergency_home"
        title="Incidents"
        titleBadge={
          <span className="font-mono-badge text-mono-badge bg-surface-container-high px-2 py-0.5 rounded text-on-surface font-medium">
            SLO Target 99.95%
          </span>
        }
        subtitle="Central triage, alert correlation, and lifecycle management for active and resolved system anomalies."
        actions={
          <>
            <Button
              variant="surface"
              icon="tune"
              onClick={() => alert('Escalation policies are governed by PagerDuty and Opsgenie integrations.')}
            >
              Escalation Policies
            </Button>
            <Button
              variant="danger"
              icon="add_alert"
              onClick={() => alert('Simulated incident declaration. Requires SRE authorization.')}
            >
              Declare Incident
            </Button>
          </>
        }
      />

      {/* 6-Card Metric KPI Array */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-space-md">
        {/* Active Incidents */}
        <div className="relative overflow-hidden rounded-xl bg-surface-container-lowest border border-outline-variant/30 p-space-md shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              Active Incidents
            </span>
            <span className="material-symbols-outlined text-[18px] text-primary">crisis_alert</span>
          </div>
          <div className="mt-space-sm flex items-baseline gap-space-xs">
            <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
              {computedKpiStats.activeCount}
            </span>
            <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-error-container text-on-error-container font-medium animate-pulse">
              Live
            </span>
          </div>
          <div className="mt-2 text-on-surface-variant font-caption-ui text-caption-ui flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-error" />
            <span>Correlated across 7 spans</span>
          </div>
        </div>

        {/* Critical Impact */}
        <div className="relative overflow-hidden rounded-xl bg-error-container/30 border border-error/25 p-space-md shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-caption-ui text-caption-ui text-error uppercase font-semibold">
              Critical Impact
            </span>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-error opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-error" />
            </span>
          </div>
          <div className="mt-space-sm flex items-baseline gap-space-xs">
            <span className="font-mono-metric-lg text-mono-metric-lg text-error font-semibold">
              {computedKpiStats.criticalImpactCount}
            </span>
            <span className="font-caption-ui text-caption-ui text-error font-semibold">
              Immediate action
            </span>
          </div>
          <div className="mt-2 text-on-surface-variant font-caption-ui text-caption-ui truncate">
            Payment &amp; checkout degraded
          </div>
        </div>

        {/* Acknowledged */}
        <div className="relative overflow-hidden rounded-xl bg-surface-container-lowest border border-outline-variant/30 p-space-md shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              Acknowledged
            </span>
            <span className="material-symbols-outlined text-[18px] text-tertiary">check_circle</span>
          </div>
          <div className="mt-space-sm flex items-baseline gap-space-xs">
            <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
              {computedKpiStats.acknowledgedCount}
            </span>
            <span className="font-caption-ui text-caption-ui text-secondary font-medium">
              Under triage
            </span>
          </div>
          <div className="mt-2 text-on-surface-variant font-caption-ui text-caption-ui">
            All assigned with on-call
          </div>
        </div>

        {/* Resolved (24h) */}
        <div className="relative overflow-hidden rounded-xl bg-surface-container-lowest border border-outline-variant/30 p-space-md shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              Resolved (24h)
            </span>
            <span className="material-symbols-outlined text-[18px] text-outline">verified</span>
          </div>
          <div className="mt-space-sm flex items-baseline gap-space-xs">
            <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
              {computedKpiStats.resolved24hCount}
            </span>
            <span className="font-mono-caption text-mono-caption text-secondary">+3 vs yesterday</span>
          </div>
          <div className="mt-2 text-on-surface-variant font-caption-ui text-caption-ui">
            100% postmortems logged
          </div>
        </div>

        {/* MTTD */}
        <div className="relative overflow-hidden rounded-xl bg-surface-container-lowest border border-outline-variant/30 p-space-md shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              MTTD
            </span>
            <span className="material-symbols-outlined text-[18px] text-primary">timer</span>
          </div>
          <div className="mt-space-sm flex items-baseline gap-space-xs">
            <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
              {computedKpiStats.mttdFormatted}
            </span>
          </div>
          <div className="mt-2 text-on-surface-variant font-caption-ui text-caption-ui flex items-center gap-1">
            <span className="text-tertiary font-mono-caption text-mono-caption">↓ 18s</span>
            <span>ahead of SLA threshold</span>
          </div>
        </div>

        {/* MTTR */}
        <div className="relative overflow-hidden rounded-xl bg-surface-container-lowest border border-outline-variant/30 p-space-md shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              MTTR
            </span>
            <span className="material-symbols-outlined text-[18px] text-primary">auto_fix_high</span>
          </div>
          <div className="mt-space-sm flex items-baseline gap-space-xs">
            <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
              {kpiStats?.mttrFormatted ?? '18m 40s'}
            </span>
          </div>
          <div className="mt-2 text-on-surface-variant font-caption-ui text-caption-ui flex items-center gap-1">
            <span className="text-secondary font-mono-caption text-mono-caption">Rolling 7-day average</span>
          </div>
        </div>
      </div>

      {/* Real-time Anomaly Stream Banner */}
      <div className="rounded-xl bg-surface-container border border-outline-variant/30 p-space-md shadow-sm flex flex-col lg:flex-row lg:items-center justify-between gap-space-md">
        <div className="flex items-center gap-space-md">
          <div className="w-10 h-10 rounded-lg bg-surface-container-highest flex items-center justify-center text-primary flex-shrink-0">
            <span className="material-symbols-outlined text-[24px]">troubleshoot</span>
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-space-xs">
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                AI Root Cause Correlation is Active
              </span>
              <span className="font-mono-badge text-mono-badge bg-primary-fixed text-on-primary-fixed-variant px-1.5 py-0.5 rounded font-medium">
                Autonomous Agent #4 (Simulated Demo)
              </span>
            </div>
            <p className="font-body-default text-body-default text-on-surface-variant mt-0.5">
              Incident <span className="font-mono-body text-mono-body font-semibold text-primary">INC-8492</span> isolated to connection exhaustion in <code className="font-mono-caption text-mono-caption bg-surface-container-highest px-1 py-0.5 rounded text-on-surface">aurora-prod-cluster-02</code>. Automated remediation playbooks available.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-space-sm self-start lg:self-auto shrink-0">
          <Button
            variant="surface"
            icon="play_circle"
            onClick={() => alert('Simulated dry-run mitigation preview: Terminate idle transactions older than 300s.')}
          >
            Preview Mitigation Script
          </Button>
          <Button
            variant="primary"
            icon="visibility"
            onClick={() => navigate('/ai-investigations')}
          >
            Open Diagnostic Canvas
          </Button>
        </div>
      </div>

      {/* Incident Operations Center: Filtering & Data Grid */}
      <div className="flex flex-col rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm overflow-hidden">
        {/* Filter Bar Header */}
        <div className="p-space-md bg-surface-container-low/60 border-b border-outline-variant/20 flex flex-col gap-space-md">
          {/* Search and Quick Facets */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md">
            {/* Search Input */}
            <div className="relative flex-1 max-w-xl">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline">
                search
              </span>
              <input
                className="w-full h-9 pl-9 pr-12 bg-surface text-on-surface placeholder:text-outline rounded-lg text-body-default font-body-default border border-outline-variant/30 focus:outline-none focus:ring-1 focus:ring-primary shadow-xs"
                placeholder="Search incidents by ID, title, affected service, responder..."
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            {/* Status Tabs */}
            <div className="flex items-center gap-space-sm flex-wrap">
              <div className="flex rounded-lg bg-surface-container p-0.5 shadow-xs text-caption-ui font-caption-ui border border-outline-variant/20">
                {(
                  [
                    { id: 'all', label: 'All' },
                    { id: 'active', label: 'Active' },
                    { id: 'detected', label: 'Detected' },
                    { id: 'investigating', label: 'Investigating' },
                    { id: 'mitigated', label: 'Mitigated' },
                    { id: 'resolved', label: 'Resolved' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setStatusFilter(tab.id)}
                    className={`px-2.5 py-1.5 rounded-lg transition-all font-medium ${
                      statusFilter === tab.id
                        ? 'bg-surface-container-lowest text-on-surface font-semibold shadow-xs'
                        : 'text-secondary hover:text-on-surface'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {/* Download dump */}
              <button
                className="h-9 w-9 rounded-lg bg-surface-container-lowest text-secondary hover:text-on-surface flex items-center justify-center shadow-xs border border-outline-variant/30 hover:bg-surface-container transition-colors"
                title="Download Telemetry Dump"
                type="button"
                onClick={() => alert('Exporting incident event logs in NDJSON format...')}
              >
                <span className="material-symbols-outlined text-[18px]">download</span>
              </button>
            </div>
          </div>

          {/* Severity Filter Badges Row */}
          <div className="flex items-center gap-space-xs flex-wrap">
            <span className="font-caption-ui text-caption-ui uppercase text-outline font-semibold mr-1">
              Severity:
            </span>

            <button
              type="button"
              onClick={() => setSeverityFilter('all')}
              className={`px-2.5 py-1 rounded-full font-mono-badge text-mono-badge font-medium transition-all ${
                severityFilter === 'all'
                  ? 'bg-surface-container-high text-on-surface font-bold'
                  : 'bg-surface-container-lowest text-secondary hover:bg-surface-container'
              }`}
            >
              All ({incidents.length})
            </button>

            <button
              type="button"
              onClick={() => setSeverityFilter('critical')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-mono-badge text-mono-badge font-medium shadow-xs transition-all ${
                severityFilter === 'critical'
                  ? 'bg-error text-on-error font-bold'
                  : 'bg-surface-container-lowest hover:bg-surface-container text-on-surface'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-error" />
              <span>Critical ({criticalCount})</span>
            </button>

            <button
              type="button"
              onClick={() => setSeverityFilter('high')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-mono-badge text-mono-badge font-medium shadow-xs transition-all ${
                severityFilter === 'high'
                  ? 'bg-tertiary text-on-tertiary font-bold'
                  : 'bg-surface-container-lowest hover:bg-surface-container text-on-surface'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-tertiary-container" />
              <span>High ({highCount})</span>
            </button>

            <button
              type="button"
              onClick={() => setSeverityFilter('medium')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-mono-badge text-mono-badge font-medium shadow-xs transition-all ${
                severityFilter === 'medium'
                  ? 'bg-secondary text-on-secondary font-bold'
                  : 'bg-surface-container-lowest hover:bg-surface-container text-on-surface'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-secondary" />
              <span>Medium ({mediumCount})</span>
            </button>

            <button
              type="button"
              onClick={() => setSeverityFilter('low')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-mono-badge text-mono-badge font-medium shadow-xs transition-all ${
                severityFilter === 'low'
                  ? 'bg-outline text-surface-container-lowest font-bold'
                  : 'bg-surface-container-lowest hover:bg-surface-container text-on-surface'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-outline" />
              <span>Low ({lowCount})</span>
            </button>
          </div>
        </div>

        {/* Data Grid Content */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="h-9 bg-surface-container-low/70 text-secondary font-caption-ui text-caption-ui uppercase tracking-wider font-semibold select-none border-b border-outline-variant/20">
                <th className="px-space-md py-2 w-28">Incident ID</th>
                <th className="px-space-md py-2 min-w-[280px]">Incident Title</th>
                <th className="px-space-md py-2 w-32">Severity</th>
                <th className="px-space-md py-2 min-w-[200px]">Affected Services</th>
                <th className="px-space-md py-2 w-36">Started At</th>
                <th className="px-space-md py-2 w-28 text-right">Duration</th>
                <th className="px-space-md py-2 w-44">Status</th>
                <th className="px-space-md py-2 min-w-[180px]">Assigned Responder</th>
                <th className="px-space-md py-2 w-36 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="text-body-default font-body-default divide-y divide-surface-container/60">
              {filteredIncidents.map((incident) => {
                const isCritical = incident.severity === 'CRITICAL';
                return (
                  <tr
                    key={incident.id}
                    onClick={() => navigate(`/incidents/${incident.id}`)}
                    className={`group transition-colors cursor-pointer ${
                      isCritical
                        ? 'bg-error-container/10 hover:bg-error-container/20'
                        : incident.status === 'RESOLVED'
                        ? 'opacity-85 hover:opacity-100 bg-surface-container-lowest hover:bg-surface-container-low'
                        : 'bg-surface-container-lowest hover:bg-surface-container-low'
                    }`}
                  >
                    <td className="px-space-md py-3.5 align-top">
                      <div className="flex flex-col gap-1 items-start">
                        <div className="flex items-center gap-1.5">
                          {isCritical ? (
                            <span className="w-1.5 h-1.5 rounded-full bg-error animate-ping" />
                          ) : (
                            <span
                              className={`w-1.5 h-1.5 rounded-full ${
                                incident.status === 'RESOLVED'
                                  ? 'bg-outline'
                                  : incident.status === 'DETECTED'
                                  ? 'bg-error animate-pulse'
                                  : 'bg-secondary'
                              }`}
                            />
                          )}
                          <span
                            className={`font-mono-body text-mono-body font-semibold ${
                              isCritical ? 'text-primary' : 'text-on-surface'
                            }`}
                          >
                            {incident.id}
                          </span>
                        </div>
                        {incident.correlationGroupId ? (
                          <span className="font-mono-badge text-[10px] px-1.5 py-0.5 rounded bg-tertiary-container/30 text-tertiary border border-tertiary/20 font-medium">
                            TELEMETRY LINKED
                          </span>
                        ) : (
                          <span className="font-mono-badge text-[10px] px-1 py-0.5 rounded bg-surface-container text-outline font-medium">
                            DEMO
                          </span>
                        )}
                      </div>
                    </td>

                    <td className="px-space-md py-3.5 align-top">
                      <div className="flex flex-col gap-1">
                        <span className="font-body-medium text-body-medium font-semibold text-on-surface group-hover:text-primary transition-colors">
                          {incident.title}
                        </span>
                        <div className="flex items-center gap-2 text-on-surface-variant font-caption-ui text-caption-ui">
                          {incident.correlationGroupId && (
                            <span className="inline-flex items-center gap-1 text-primary font-medium">
                              <span className="material-symbols-outlined text-[14px]">hub</span>
                              Multi-Signal RCA
                            </span>
                          )}
                          {incident.correlationGroupId && <span>•</span>}
                          <span>
                            {incident.rootCauseSummary || 'Root cause under autonomous correlation'}
                          </span>
                        </div>
                      </div>
                    </td>

                    <td className="px-space-md py-3.5 align-top">
                      <span
                        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg font-mono-badge text-mono-badge font-semibold uppercase ${
                          incident.severity === 'CRITICAL'
                            ? 'bg-error-container text-on-error-container'
                            : incident.severity === 'HIGH'
                            ? 'bg-secondary-container text-on-secondary-fixed'
                            : incident.severity === 'MEDIUM'
                            ? 'bg-surface-container-high text-on-surface'
                            : 'bg-surface-container text-outline'
                        }`}
                      >
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            incident.severity === 'CRITICAL'
                              ? 'bg-error'
                              : incident.severity === 'HIGH'
                              ? 'bg-tertiary-container'
                              : incident.severity === 'MEDIUM'
                              ? 'bg-secondary'
                              : 'bg-outline'
                          }`}
                        />
                        {incident.severity}
                      </span>
                    </td>

                    <td className="px-space-md py-3.5 align-top">
                      <div className="flex flex-wrap gap-1">
                        {incident.affectedServices.map((svc) => (
                          <span
                            key={svc}
                            className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant"
                          >
                            {svc}
                          </span>
                        ))}
                      </div>
                    </td>

                    <td className="px-space-md py-3.5 align-top font-mono-body text-mono-body text-on-surface-variant">
                      <div>{incident.startedAt}</div>
                    </td>

                    <td className="px-space-md py-3.5 align-top text-right font-mono-body text-mono-body font-medium text-on-surface">
                      {incident.activeDuration}
                    </td>

                    <td className="px-space-md py-3.5 align-top">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-mono-badge text-mono-badge font-semibold ${
                          incident.status === 'DETECTED'
                            ? 'bg-error-container text-on-error-container'
                            : incident.status === 'INVESTIGATING'
                            ? 'bg-primary-fixed text-on-primary-fixed-variant'
                            : incident.status === 'ACKNOWLEDGED'
                            ? 'bg-secondary-container text-on-secondary-fixed'
                            : incident.status === 'MITIGATED'
                            ? 'bg-surface-container text-on-surface-variant'
                            : 'bg-surface-container-low text-secondary'
                        }`}
                      >
                        <span className="material-symbols-outlined text-[13px]">
                          {incident.status === 'RESOLVED'
                            ? 'check_circle'
                            : incident.status === 'MITIGATED'
                            ? 'shield'
                            : incident.status === 'DETECTED'
                            ? 'sensors'
                            : 'psychology'}
                        </span>
                        {incident.status}
                      </span>
                    </td>

                    <td className="px-space-md py-3.5 align-top">
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-6 rounded-full bg-surface-container-high flex items-center justify-center font-caption-ui text-caption-ui font-semibold text-on-surface shrink-0">
                          {incident.commander.name
                            .split(' ')
                            .map((p) => p[0])
                            .join('')}
                        </div>
                        <div className="flex flex-col truncate">
                          <span className="font-body-medium text-body-medium text-on-surface font-medium leading-tight truncate">
                            {incident.commander.name}
                          </span>
                          <span className="font-caption-ui text-caption-ui text-outline leading-tight truncate">
                            {incident.commander.role}
                          </span>
                        </div>
                      </div>
                    </td>

                    <td className="px-space-md py-3.5 align-top text-right" onClick={(e) => e.stopPropagation()}>
                      <Button
                        variant={isCritical ? 'primary' : 'surface'}
                        size="sm"
                        onClick={() => navigate(`/incidents/${incident.id}`)}
                      >
                        {isCritical ? 'War Room' : incident.status === 'RESOLVED' ? 'Postmortem' : 'Details'}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Table Footer */}
        <div className="px-space-md py-3 bg-surface-container-low/50 flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm font-caption-ui text-caption-ui text-secondary border-t border-outline-variant/20">
          <div className="flex items-center gap-space-xs">
            <span className="w-2 h-2 rounded-full bg-tertiary" />
            <span>
              Showing {filteredIncidents.length} of {incidents.length} incidents
            </span>
            <span className="text-outline">•</span>
            <span className="font-mono-caption text-mono-caption">Simulated Live Incident Queue</span>
          </div>
          <div className="flex items-center gap-space-sm self-end sm:self-auto">
            <span>Rows per page: 25</span>
          </div>
        </div>
      </div>

      {/* Incident Timeline Correlation Visualizer (Context Dock) */}
      <div className="rounded-xl bg-surface-container-lowest border border-outline-variant/30 p-space-md shadow-sm flex flex-col gap-space-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-space-xs">
            <span className="material-symbols-outlined text-[18px] text-primary">hub</span>
            <span className="font-title-md text-title-md text-on-surface font-semibold">
              Active Anomaly Propagation Graph
            </span>
            <span className="font-mono-badge text-mono-badge bg-surface-container px-1.5 py-0.5 rounded text-secondary">
              Cluster Topology
            </span>
          </div>
          <span className="font-mono-caption text-mono-caption text-outline">
            Correlated Live Spans (INC-8492)
          </span>
        </div>

        {/* Telemetry SVG Propagation Graph matching Stitch design */}
        <div className="w-full bg-surface-container-low/70 rounded-lg p-space-sm flex flex-col gap-2 border border-outline-variant/20">
          <div className="flex items-center justify-between text-caption-ui font-caption-ui text-secondary px-1">
            <span>Entryway: api-gateway (us-east-1)</span>
            <span className="font-mono-caption text-mono-caption text-error font-medium">
              Degradation: Aurora Pool &gt; 98% load (980/1000)
            </span>
          </div>

          <div className="w-full h-16 relative flex items-center justify-between px-6">
            {/* SVG Connecting Flow lines */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none" xmlns="http://www.w3.org/2000/svg">
              <line
                className="text-tertiary-container"
                stroke="currentColor"
                strokeDasharray="3 3"
                strokeWidth="2"
                x1="12%"
                x2="38%"
                y1="50%"
                y2="50%"
              />
              <line
                className="text-error"
                stroke="currentColor"
                strokeDasharray="3 3"
                strokeWidth="2"
                x1="38%"
                x2="68%"
                y1="50%"
                y2="50%"
              />
              <line
                className="text-error"
                stroke="currentColor"
                strokeDasharray="3 3"
                strokeWidth="2"
                x1="68%"
                x2="90%"
                y1="50%"
                y2="50%"
              />
            </svg>

            {/* Node 1 */}
            <div className="relative z-10 flex flex-col items-center">
              <div className="px-2.5 py-1 rounded bg-surface-container-lowest shadow-sm font-mono-badge text-mono-badge text-on-surface font-semibold flex items-center gap-1 border border-outline-variant/20">
                <span className="w-2 h-2 rounded-full bg-tertiary" /> api-gateway
              </div>
              <span className="font-mono-caption text-mono-caption text-secondary mt-1">200 OK (97.1%)</span>
            </div>

            {/* Node 2 */}
            <div className="relative z-10 flex flex-col items-center">
              <div className="px-2.5 py-1 rounded bg-surface-container-lowest shadow-sm font-mono-badge text-mono-badge text-on-surface font-semibold flex items-center gap-1 border border-outline-variant/20">
                <span className="w-2 h-2 rounded-full bg-secondary" /> order-service
              </div>
              <span className="font-mono-caption text-mono-caption text-secondary mt-1">502 Errors (4.12%)</span>
            </div>

            {/* Node 3 (Spill Cascade) */}
            <div className="relative z-10 flex flex-col items-center">
              <div className="px-2.5 py-1 rounded bg-error-container text-on-error-container shadow-sm font-mono-badge text-mono-badge font-semibold flex items-center gap-1 animate-pulse border border-error/30">
                <span className="w-2 h-2 rounded-full bg-error" /> payment-service
              </div>
              <span className="font-mono-caption text-mono-caption text-error font-medium mt-1">
                Timeout (8.85%)
              </span>
            </div>

            {/* Node 4 (Root Cause) */}
            <div className="relative z-10 flex flex-col items-center">
              <div className="px-2.5 py-1 rounded bg-error text-on-error shadow-sm font-mono-badge text-mono-badge font-bold flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-surface-bright animate-ping" /> aurora-db
              </div>
              <span className="font-mono-caption text-mono-caption text-error font-bold mt-1">
                Pool: 980/1000 (98%)
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
