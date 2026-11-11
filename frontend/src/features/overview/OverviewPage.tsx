import React, { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  AreaChart,
  Area
} from 'recharts';
import { PageHeader } from '../../components/layout/PageHeader';
import { KpiCard, Button, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { ServiceItem, IncidentItem, TelemetryOverviewData } from '../../types';

export const OverviewPage: React.FC = () => {
  const navigate = useNavigate();

  const [timeRange, setTimeRange] = useState<'15m' | '1h' | '24h'>('15m');
  const [telemetry, setTelemetry] = useState<TelemetryOverviewData | null>(null);
  const [services, setServices] = useState<ServiceItem[]>([]);
  const [incidents, setIncidents] = useState<IncidentItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<{ message: string; details?: Record<string, unknown> } | null>(null);

  // Table filter states
  const [serviceSearch, setServiceSearch] = useState<string>('');
  const [serviceFilter, setServiceFilter] = useState<'all' | 'issues'>('all');

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getTelemetryOverview(timeRange),
      apiClient.getServices(),
      apiClient.getIncidents(),
    ])
      .then(([telemetryRes, servicesRes, incidentsRes]) => {
        if (!mounted) return;
        setTelemetry(telemetryRes.data);
        setServices(servicesRes.data);
        setIncidents(incidentsRes.data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!mounted) return;
        const e = err as { message?: string; details?: Record<string, unknown> };
        setError({
          message: e.message || 'Failed to load overview monitoring metrics',
          details: e.details,
        });
        setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [timeRange]);

  // Dynamic Fleet & Incident counts
  const healthyCount = useMemo(() => services.filter((s) => s.status === 'healthy').length, [services]);
  const degradedCount = useMemo(() => services.filter((s) => s.status === 'degraded').length, [services]);
  const unhealthyCount = useMemo(() => services.filter((s) => s.status === 'unhealthy').length, [services]);
  const totalFleetCount = services.length || 10;

  const activeIncidents = useMemo(() => incidents.filter((i) => i.status !== 'RESOLVED'), [incidents]);
  const criticalActiveIncidents = useMemo(() => activeIncidents.filter((i) => i.severity === 'CRITICAL'), [activeIncidents]);

  // Filtered services for the fleet table
  const filteredServices = useMemo(() => {
    return services.filter((svc) => {
      const matchesSearch =
        svc.name.toLowerCase().includes(serviceSearch.toLowerCase()) ||
        svc.identifier.toLowerCase().includes(serviceSearch.toLowerCase());
      if (!matchesSearch) return false;
      if (serviceFilter === 'issues') {
        return svc.status === 'degraded' || svc.status === 'unhealthy';
      }
      return true;
    });
  }, [services, serviceSearch, serviceFilter]);

  const formatRps = (val?: number | null) => {
    if (val === null || val === undefined) return 'Unavailable';
    const num = Number(val);
    if (num >= 1000) return `${(num / 1000).toFixed(1)}k req/s`;
    return `${num.toFixed(1)} req/s`;
  };

  const requestRateDisplay =
    telemetry?.requestRateStatus === 'insufficient_data'
      ? 'Insufficient data'
      : telemetry?.requestRateStatus === 'no_traffic'
      ? '0.0 req/s'
      : formatRps(telemetry?.currentThroughputRps);

  const requestRateSubtitle =
    telemetry?.requestRateStatus === 'insufficient_data'
      ? 'Need >=1s span or request_rate sample'
      : telemetry?.requestRateStatus === 'no_traffic'
      ? 'No application requests in window'
      : `Peak: ${formatRps(telemetry?.peakThroughputRps)}`;

  const maxObservedP99Ms = useMemo(() => {
    const pts = telemetry?.points || [];
    if (pts.length === 0) return 0;
    return Math.round(Math.max(...pts.map((p) => Number(p.p99Ms ?? 0))));
  }, [telemetry]);

  const overallHealthLabel =
    unhealthyCount > 0 ? 'Unhealthy' : degradedCount > 0 ? 'Degraded' : 'Healthy';
  const primaryActiveIncident = activeIncidents[0] || null;
  const warRoomTargetId = primaryActiveIncident?.id || incidents[0]?.id || 'INC-8492';

  if (loading && !telemetry) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <LoadingSpinner message="Aggregating live cluster telemetry and active incident stream..." fullScreen />
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <ErrorState
          title="Telemetry Ingestion Error"
          message={error.message}
          details={error.details}
          onRetry={() => setTimeRange(timeRange)}
        />
      </div>
    );
  }

  return (
    <div className="w-full px-margin-desktop py-margin-desktop space-y-space-lg">
      {/* Page Header */}
      <PageHeader
        category="Observability Command"
        categoryIcon="monitoring"
        title="Overview"
        titleBadge={
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-error-container text-on-error-container font-mono-badge text-mono-badge uppercase tracking-wider font-semibold">
            <span className="w-1.5 h-1.5 rounded-full bg-error animate-ping" />
            Incident Mode Active
          </span>
        }
        subtitle="Monitor your application's health, latency, and active incidents in real time."
        actions={
          <>
            {/* Time-Range Selector */}
            <div className="inline-flex items-center bg-surface-container rounded-lg p-0.5 border border-outline-variant/30 text-caption-ui font-caption-ui">
              {(['15m', '1h', '24h'] as const).map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setTimeRange(r)}
                  className={`px-2.5 py-1 rounded transition-colors font-medium ${
                    timeRange === r
                      ? 'bg-surface-container-lowest text-primary shadow-xs'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  {r === '15m' ? '15m' : r === '1h' ? '1h' : '24h'}
                </button>
              ))}
            </div>

            <div className="inline-flex items-center gap-2 px-space-sm py-1.5 rounded-lg bg-surface-container text-on-surface font-mono-caption text-mono-caption">
              <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
              <span>Live Stream: ON (30s)</span>
            </div>

            <Button
              variant="secondary"
              icon="crisis_alert"
              onClick={() => navigate('/incidents')}
            >
              Incidents ({activeIncidents.length})
            </Button>

            <Button
              variant="primary"
              icon="auto_awesome"
              onClick={() => navigate(`/incidents/${warRoomTargetId}`)}
            >
              Launch War Room
            </Button>
          </>
        }
      />

      {/* 6-Card KPI Array Matching Stitch Export */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-space-sm">
        <KpiCard
          title="Overall Health"
          value={overallHealthLabel}
          badge={
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-secondary-container text-on-secondary-fixed-variant font-mono-badge text-mono-badge font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-tertiary-container" />
              SLO
            </span>
          }
          subtitle={`${healthyCount}/${totalFleetCount} healthy services`}
          indicator={
            <div className="w-full bg-surface-container-high h-1.5 rounded-full overflow-hidden mt-2">
              <div
                className="bg-primary h-full rounded-full"
                style={{ width: `${Math.round((healthyCount / Math.max(1, totalFleetCount)) * 100)}%` }}
              />
            </div>
          }
        />

        <KpiCard
          title="Active Incidents"
          value={`${activeIncidents.length} Active`}
          valueColor="text-error"
          icon="warning"
          iconColor="text-error"
          badge={
            <span className="font-mono-caption text-mono-caption px-1.5 py-0.2 rounded bg-error-container text-on-error-container font-medium">
              {criticalActiveIncidents.length} Critical
            </span>
          }
          subtitle={`${activeIncidents.length - criticalActiveIncidents.length} Medium/High · Escalation active`}
          trend="Escalation active"
          trendDirection="up"
          onClick={() => navigate('/incidents')}
        />

        <KpiCard
          title="Monitored Fleet"
          value={`${totalFleetCount}`}
          icon="lan"
          iconColor="text-secondary"
          subtitle={`${healthyCount} OK · ${degradedCount} Degraded · ${unhealthyCount} Fail`}
          indicator={
            <div className="flex h-1.5 w-full rounded-full overflow-hidden bg-surface-container-high gap-0.5 mt-2">
              <div className="bg-primary h-full transition-all" style={{ width: `${(healthyCount / totalFleetCount) * 100}%` }} />
              <div className="bg-tertiary-container h-full transition-all" style={{ width: `${(degradedCount / totalFleetCount) * 100}%` }} />
              <div className="bg-error h-full transition-all" style={{ width: `${(unhealthyCount / totalFleetCount) * 100}%` }} />
            </div>
          }
          onClick={() => navigate('/services')}
        />

        <KpiCard
          title="Error Rate"
          value={`${Number(telemetry?.currentErrorRatePercent ?? 0).toFixed(2)}%`}
          valueColor={(telemetry?.currentErrorRatePercent ?? 0) > 1.0 ? 'text-error' : 'text-on-surface'}
          badge={
            <span className="px-1.5 py-0.5 rounded bg-error-container text-on-error-container font-mono-badge text-mono-badge font-semibold">
              Peak {Number(telemetry?.peakErrorRatePercent ?? 0).toFixed(2)}%
            </span>
          }
          subtitle="Window error rate"
          trend={(telemetry?.currentErrorRatePercent ?? 0) > 1.0 ? 'Exceeds 1.0% threshold' : 'Nominal range'}
          trendDirection={(telemetry?.currentErrorRatePercent ?? 0) > 1.0 ? 'up' : 'neutral'}
        />

        <KpiCard
          title="Request Rate"
          value={requestRateDisplay}
          badge={
            <span className="px-1.5 py-0.5 rounded bg-secondary-container text-on-secondary-fixed-variant font-mono-badge text-mono-badge font-semibold">
              {telemetry?.totalRequests ?? 0} reqs
            </span>
          }
          subtitle={requestRateSubtitle}
          trend={
            telemetry?.requestRateStatus === 'available'
              ? `Mean ${formatRps(telemetry?.meanThroughputRps)}`
              : 'Waiting for request samples'
          }
          trendDirection="neutral"
        />

        <KpiCard
          title="P95 Latency"
          value={`${Number(telemetry?.currentP95Ms ?? 0).toFixed(1)} ms`}
          valueColor={(telemetry?.currentP95Ms ?? 0) > 250 ? 'text-tertiary' : 'text-on-surface'}
          badge={
            <span className="px-1.5 py-0.5 rounded bg-surface-container-highest text-tertiary font-mono-badge text-mono-badge font-semibold">
              P99 {Number(telemetry?.currentP99Ms ?? 0).toFixed(0)}ms
            </span>
          }
          subtitle={`Baseline ${Number(telemetry?.baselineP95Ms ?? 0).toFixed(1)} ms`}
          trend={(telemetry?.currentP95Ms ?? 0) > (telemetry?.baselineP95Ms ?? 0) * 2 ? 'Elevated tail latency' : 'Within baseline'}
          trendDirection={(telemetry?.currentP95Ms ?? 0) > (telemetry?.baselineP95Ms ?? 0) * 2 ? 'up' : 'neutral'}
        />
      </div>

      {/* Critical Anomaly Incident Banner */}
      {primaryActiveIncident && (
        <div className="p-space-md rounded-xl bg-error-container/40 text-on-error-container border border-error/20 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-space-md">
          <div className="flex items-start gap-space-sm">
            <span className="material-symbols-outlined text-[24px] text-error mt-0.5 shrink-0">
              notification_important
            </span>
            <div className="flex flex-col">
              <div className="flex items-center gap-space-xs flex-wrap">
                <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-error text-on-error uppercase font-bold">
                  {primaryActiveIncident.severity}
                </span>
                <span className="font-title-md text-title-md font-semibold text-on-surface">
                  {primaryActiveIncident.id}: {primaryActiveIncident.title}
                </span>
                <span className="font-mono-caption text-mono-caption text-on-surface-variant">
                  Started {primaryActiveIncident.startedAt} · {primaryActiveIncident.activeDuration}
                </span>
              </div>
              <p className="font-body-default text-body-default text-on-surface-variant mt-1">
                Impacted:{' '}
                <span className="font-semibold text-on-surface">
                  {primaryActiveIncident.affectedServices.join(', ') || 'Monitored services'}
                </span>
                . {primaryActiveIncident.rootCauseSummary || primaryActiveIncident.summary}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-space-xs shrink-0 w-full md:w-auto justify-end">
            <Button
              variant="surface"
              icon="insights"
              onClick={() => navigate('/traces')}
            >
              Investigate in Traces
            </Button>
            <Button
              variant="danger"
              icon="auto_awesome"
              onClick={() => navigate(`/incidents/${primaryActiveIncident.id}`)}
            >
              Open War Room
            </Button>
          </div>
        </div>
      )}

      {/* 3 Telemetry Time-Series Charts with Recharts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-space-md">
        {/* Chart 1: Request Rate (req/s) */}
        <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between mb-space-sm">
            <div className="flex flex-col">
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                Request Rate (req/s)
              </span>
              <span className="font-mono-caption text-mono-caption text-on-surface-variant">
                Scope: {timeRange} • Dashed line is baseline
              </span>
            </div>
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 bg-surface-container text-on-surface-variant rounded">
              Mean {formatRps(telemetry?.meanThroughputRps)}
            </span>
          </div>

          <div className="w-full h-44 bg-surface-container-low/60 rounded-lg p-2 flex flex-col justify-between">
            <div className="flex justify-between font-mono-caption text-mono-caption text-outline mb-1">
              <span>Peak: {formatRps(telemetry?.peakThroughputRps)}</span>
              <span className="text-primary font-semibold">
                Current: {formatRps(telemetry?.currentThroughputRps)}
              </span>
            </div>
            <div className="w-full h-32">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={telemetry?.points || []} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 2" stroke="#c7c4d8" opacity={0.3} />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10, fill: '#777587', fontFamily: 'JetBrains Mono' }}
                    stroke="#c7c4d8"
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: '#777587', fontFamily: 'JetBrains Mono' }}
                    stroke="#c7c4d8"
                    tickLine={false}
                    tickFormatter={(val) => (val >= 1000 ? `${(val / 1000).toFixed(0)}k` : `${val}`)}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#ffffff',
                      borderColor: '#c7c4d8',
                      borderRadius: '8px',
                      fontSize: '11px',
                      fontFamily: 'JetBrains Mono',
                      boxShadow: '0 4px 12px rgba(11,28,48,0.08)'
                    }}
                    formatter={(value: any, name: any) => [
                      `${Number(value).toLocaleString()} req/s`,
                      name === 'throughputRps' ? 'Live Throughput' : 'Baseline'
                    ]}
                  />
                  <Line
                    type="monotone"
                    dataKey="baselineThroughputRps"
                    stroke="#565e74"
                    strokeWidth={1.5}
                    strokeDasharray="4 4"
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="throughputRps"
                    stroke="#3525cd"
                    strokeWidth={2.2}
                    dot={{ r: 2, fill: '#3525cd' }}
                    activeDot={{ r: 5, fill: '#3525cd' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="flex items-center justify-between pt-space-xs font-mono-caption text-mono-caption text-on-surface-variant">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-primary rounded-full" /> Live Throughput
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-secondary border-dashed rounded-full" /> Baseline Reference
            </span>
          </div>
        </div>

        {/* Chart 2: Error Rate (%) */}
        <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between mb-space-sm">
            <div className="flex flex-col">
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                Error Rate (%)
              </span>
              <span className="font-mono-caption text-mono-caption text-on-surface-variant">
                Scope: {timeRange} • 1.0% error budget threshold
              </span>
            </div>
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 bg-error-container text-on-error-container font-semibold rounded">
              Peak {Number(telemetry?.peakErrorRatePercent ?? 0).toFixed(2)}%
            </span>
          </div>

          <div className="w-full h-44 bg-surface-container-low/60 rounded-lg p-2 flex flex-col justify-between">
            <div className="flex justify-between font-mono-caption text-mono-caption text-outline mb-1">
              <span>Threshold: 1.0%</span>
              <span className={(telemetry?.peakErrorRatePercent ?? 0) > 1.0 ? 'text-error font-semibold' : 'text-on-surface-variant'}>
                {(telemetry?.peakErrorRatePercent ?? 0) > 1.0 ? 'Threshold Breached' : 'Within Threshold'}
              </span>
            </div>
            <div className="w-full h-32">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={telemetry?.points || []} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 2" stroke="#c7c4d8" opacity={0.3} />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10, fill: '#777587', fontFamily: 'JetBrains Mono' }}
                    stroke="#c7c4d8"
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: '#777587', fontFamily: 'JetBrains Mono' }}
                    stroke="#c7c4d8"
                    tickLine={false}
                    tickFormatter={(val) => `${val}%`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#ffffff',
                      borderColor: '#ffdad6',
                      borderRadius: '8px',
                      fontSize: '11px',
                      fontFamily: 'JetBrains Mono',
                      boxShadow: '0 4px 12px rgba(186,26,26,0.1)'
                    }}
                    formatter={(val: any) => [`${val}%`, 'Error Rate']}
                  />
                  <Area
                    type="monotone"
                    dataKey="errorRatePercent"
                    stroke="#ba1a1a"
                    strokeWidth={2.2}
                    fill="#ba1a1a"
                    fillOpacity={0.15}
                    dot={{ r: 2, fill: '#ba1a1a' }}
                    activeDot={{ r: 5, fill: '#ba1a1a' }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="flex items-center justify-between pt-space-xs font-mono-caption text-mono-caption text-on-surface-variant">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-error" /> HTTP 5xx / Application Errors
            </span>
            <span className={(telemetry?.currentErrorRatePercent ?? 0) > 1.0 ? 'text-error font-medium' : 'text-on-surface-variant'}>
              {(telemetry?.currentErrorRatePercent ?? 0) > 1.0 ? 'Breach (>1.0%)' : 'Nominal (<=1.0%)'}
            </span>
          </div>
        </div>

        {/* Chart 3: Latency Percentiles (ms) */}
        <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between mb-space-sm">
            <div className="flex flex-col">
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                Latency Percentiles (ms)
              </span>
              <span className="font-mono-caption text-mono-caption text-on-surface-variant">
                P50, P90, P95, P99 response latency quantiles
              </span>
            </div>
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 bg-surface-container-highest text-tertiary font-semibold rounded">
              P99: {Number(telemetry?.currentP99Ms ?? 0).toFixed(1)}ms
            </span>
          </div>

          <div className="w-full h-44 bg-surface-container-low/60 rounded-lg p-2 flex flex-col justify-between">
            <div className="flex justify-between font-mono-caption text-mono-caption text-outline mb-1">
              <span>Max P99: {maxObservedP99Ms}ms</span>
              <span className="text-tertiary font-medium">
                P95: {Number(telemetry?.currentP95Ms ?? 0).toFixed(1)}ms
              </span>
            </div>
            <div className="w-full h-32">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={telemetry?.points || []} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 2" stroke="#c7c4d8" opacity={0.3} />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10, fill: '#777587', fontFamily: 'JetBrains Mono' }}
                    stroke="#c7c4d8"
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: '#777587', fontFamily: 'JetBrains Mono' }}
                    stroke="#c7c4d8"
                    tickLine={false}
                    tickFormatter={(val) => `${val}`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#ffffff',
                      borderColor: '#c7c4d8',
                      borderRadius: '8px',
                      fontSize: '11px',
                      fontFamily: 'JetBrains Mono',
                      boxShadow: '0 4px 12px rgba(11,28,48,0.08)'
                    }}
                  />
                  <Line type="monotone" dataKey="p50Ms" stroke="#565e74" strokeWidth={1.2} dot={false} name="P50" />
                  <Line type="monotone" dataKey="p90Ms" stroke="#4f46e5" strokeWidth={1.4} dot={false} name="P90" />
                  <Line type="monotone" dataKey="p95Ms" stroke="#003fac" strokeWidth={2.0} dot={false} name="P95" />
                  <Line type="monotone" dataKey="p99Ms" stroke="#ba1a1a" strokeWidth={2.0} dot={false} name="P99" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="flex items-center justify-between pt-space-xs font-mono-caption text-mono-caption text-on-surface-variant flex-wrap gap-1">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-secondary" /> P50
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-primary-container" /> P90
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-tertiary" /> P95
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-error" /> P99
            </span>
          </div>
        </div>
      </div>

      {/* Service Health Fleet Table */}
      <div className="flex flex-col bg-surface-container-lowest rounded-xl border border-outline-variant/30 shadow-sm overflow-hidden">
        <div className="p-space-md flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm bg-surface-container-lowest border-b border-outline-variant/20">
          <div className="flex items-center gap-space-sm">
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              Service Health Fleet
            </span>
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded-full bg-surface-container text-on-surface-variant font-medium">
              {filteredServices.length} entities displayed
            </span>
          </div>

          <div className="flex items-center gap-space-xs flex-wrap">
            <div className="relative min-w-[220px]">
              <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-[16px] text-outline">
                search
              </span>
              <input
                className="w-full h-8 pl-8 pr-3 bg-surface text-on-surface text-body-default font-body-default rounded-lg border border-outline-variant/40 focus:outline-none focus:ring-1 focus:ring-primary/20 transition-all placeholder:text-outline"
                placeholder="Filter service by name..."
                type="text"
                value={serviceSearch}
                onChange={(e) => setServiceSearch(e.target.value)}
              />
            </div>

            <div className="flex rounded-lg bg-surface-container p-0.5 font-body-medium text-body-medium">
              <button
                className={`px-2.5 py-1 rounded transition-colors font-medium ${
                  serviceFilter === 'all'
                    ? 'bg-surface-container-lowest text-on-surface shadow-xs'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
                type="button"
                onClick={() => setServiceFilter('all')}
              >
                All
              </button>
              <button
                className={`px-2.5 py-1 rounded transition-colors font-medium ${
                  serviceFilter === 'issues'
                    ? 'bg-surface-container-lowest text-on-surface shadow-xs'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
                type="button"
                onClick={() => setServiceFilter('issues')}
              >
                Issues ({services.filter((s) => s.status !== 'healthy').length})
              </button>
            </div>
          </div>
        </div>

        <div className="w-full overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-low text-on-surface-variant font-caption-ui text-caption-ui uppercase tracking-wider border-b border-outline-variant/20">
                <th className="py-2.5 px-space-md font-semibold">Service</th>
                <th className="py-2.5 px-space-md font-semibold">Environment</th>
                <th className="py-2.5 px-space-md font-semibold">Status</th>
                <th className="py-2.5 px-space-md font-semibold text-right">Throughput</th>
                <th className="py-2.5 px-space-md font-semibold text-right">Error Rate</th>
                <th className="py-2.5 px-space-md font-semibold text-right">P95 Latency</th>
                <th className="py-2.5 px-space-md font-semibold text-right">Last Deployment</th>
                <th className="py-2.5 px-space-md font-semibold text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container text-body-default font-body-default text-on-surface">
              {filteredServices.map((svc) => (
                <tr
                  key={svc.id}
                  className={`hover:bg-surface-container-low/60 transition-colors ${
                    svc.status === 'unhealthy'
                      ? 'bg-error-container/15'
                      : svc.status === 'degraded'
                      ? 'bg-surface-container-low/30'
                      : ''
                  }`}
                >
                  <td className="py-3 px-space-md font-medium flex items-center gap-space-xs">
                    <span
                      className={`material-symbols-outlined text-[18px] ${
                        svc.status === 'unhealthy'
                          ? 'text-error'
                          : svc.status === 'degraded'
                          ? 'text-tertiary'
                          : 'text-secondary'
                      }`}
                    >
                      {svc.identifier.startsWith('db:')
                        ? 'database'
                        : svc.name.includes('Order')
                        ? 'shopping_cart'
                        : svc.name.includes('Payment')
                        ? 'credit_card'
                        : svc.name.includes('Notification')
                        ? 'forward_to_inbox'
                        : 'dns'}
                    </span>
                    <div>
                      <span className="font-semibold text-on-surface block leading-tight">
                        {svc.name}
                      </span>
                      <span className="font-mono-caption text-mono-caption text-outline">
                        {svc.identifier}
                      </span>
                    </div>
                  </td>

                  <td className="py-3 px-space-md">
                    <span className="font-mono-caption text-mono-caption px-2 py-0.5 rounded bg-surface-container text-on-surface-variant">
                      {svc.environment}
                    </span>
                  </td>

                  <td className="py-3 px-space-md">
                    {svc.status === 'healthy' && (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-secondary-container text-on-secondary-fixed font-mono-badge text-mono-badge font-semibold">
                        <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                        Healthy
                      </span>
                    )}
                    {svc.status === 'degraded' && (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-tertiary-fixed text-on-tertiary-fixed-variant font-mono-badge text-mono-badge font-semibold">
                        <span className="w-1.5 h-1.5 rounded-full bg-tertiary" />
                        Degraded
                      </span>
                    )}
                    {svc.status === 'unhealthy' && (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-error text-on-error font-mono-badge text-mono-badge font-semibold">
                        <span className="w-1.5 h-1.5 rounded-full bg-surface-bright animate-ping" />
                        Failing
                      </span>
                    )}
                  </td>

                  <td className="py-3 px-space-md text-right font-mono-body text-mono-body text-on-surface">
                    {svc.requestRateRps.toLocaleString()} {svc.identifier.startsWith('db:') ? 'qps' : 'rps'}
                  </td>

                  <td
                    className={`py-3 px-space-md text-right font-mono-body text-mono-body ${
                      svc.errorRatePercent > 1.0 ? 'text-error font-semibold' : 'text-on-surface-variant'
                    }`}
                  >
                    {svc.errorRatePercent.toFixed(2)}%
                  </td>

                  <td
                    className={`py-3 px-space-md text-right font-mono-body text-mono-body ${
                      svc.p95LatencyMs > 500 ? 'text-error font-semibold' : svc.p95LatencyMs > 100 ? 'text-tertiary font-medium' : 'text-on-surface-variant'
                    }`}
                  >
                    {svc.p95LatencyMs}ms
                  </td>

                  <td className="py-3 px-space-md text-right font-mono-caption text-mono-caption text-on-surface-variant">
                    {svc.lastDeployment || 'N/A'}
                  </td>

                  <td className="py-3 px-space-md text-center">
                    <button
                      className="p-1 hover:bg-surface-container rounded text-outline hover:text-on-surface transition-colors"
                      title={`Inspect ${svc.name}`}
                      type="button"
                      onClick={() => navigate('/services')}
                    >
                      <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent Incidents Card Matching Stitch */}
      <div className="flex flex-col bg-surface-container-lowest rounded-xl border border-outline-variant/30 shadow-sm p-space-md">
        <div className="flex items-center justify-between mb-space-sm">
          <div className="flex items-center gap-space-sm">
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
              Recent Incidents &amp; Active War Rooms
            </span>
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-surface-container text-on-surface-variant">
              Live Audit Log
            </span>
          </div>
          <button
            className="font-body-medium text-body-medium text-primary hover:underline inline-flex items-center gap-1 cursor-pointer"
            type="button"
            onClick={() => navigate('/incidents')}
          >
            <span>View all incidents</span>
            <span className="material-symbols-outlined text-[16px]">arrow_forward</span>
          </button>
        </div>

        <div className="flex flex-col gap-space-xs">
          {incidents.slice(0, 3).map((incident) => (
            <div
              key={incident.id}
              className="p-space-sm rounded-lg bg-surface-container-low hover:bg-surface-container flex flex-col md:flex-row md:items-center justify-between gap-space-sm transition-colors border border-outline-variant/15"
            >
              <div className="flex items-start md:items-center gap-space-sm">
                <span
                  className={`font-mono-caption text-mono-caption font-semibold px-2 py-1 rounded ${
                    incident.severity === 'CRITICAL'
                      ? 'bg-error text-on-error'
                      : incident.severity === 'HIGH'
                      ? 'bg-tertiary text-on-tertiary'
                      : 'bg-surface-container text-on-surface'
                  }`}
                >
                  {incident.id}
                </span>
                <span
                  className={`font-mono-badge text-mono-badge uppercase px-1.5 py-0.5 rounded font-semibold ${
                    incident.severity === 'CRITICAL'
                      ? 'bg-error-container text-on-error-container'
                      : 'bg-surface-container-high text-on-surface'
                  }`}
                >
                  {incident.severity}
                </span>
                <div className="flex flex-col">
                  <span className="font-body-medium text-body-medium text-on-surface font-semibold">
                    {incident.title}
                  </span>
                  <span className="font-mono-caption text-mono-caption text-on-surface-variant">
                    Impacts {incident.affectedServices.join(', ')} • Started {incident.startedAt} ({incident.activeDuration})
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-space-sm self-end md:self-auto">
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-container-highest text-primary font-mono-badge text-mono-badge font-medium">
                  <span className="material-symbols-outlined text-[12px]">psychology</span>
                  {incident.status} {incident.aiRemediationAvailable && '(AI Active)'}
                </span>
                <Button
                  variant={incident.severity === 'CRITICAL' ? 'primary' : 'surface'}
                  size="sm"
                  onClick={() => navigate(`/incidents/${incident.id}`)}
                >
                  {incident.severity === 'CRITICAL' ? 'War Room' : 'Details'}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
