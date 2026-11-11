import React, { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { ServiceItem, ServicesOverviewStats } from '../../types';

type SortField = 'name' | 'requestRateRps' | 'errorRatePercent' | 'p95LatencyMs';
type SortOrder = 'asc' | 'desc';

export const ServicesPage: React.FC = () => {
  const navigate = useNavigate();

  const [services, setServices] = useState<ServiceItem[]>([]);
  const [stats, setStats] = useState<ServicesOverviewStats | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<{ message: string; details?: Record<string, unknown> } | null>(null);

  // Filters & Search
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedTier, setSelectedTier] = useState<'all' | '0' | '1' | '2'>('all');
  const [selectedStatus, setSelectedStatus] = useState<'all' | 'healthy' | 'degraded' | 'unhealthy'>('all');
  const [sortField, setSortField] = useState<SortField>('requestRateRps');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');

  // Selected Service for slide-out detail drawer
  const [selectedService, setSelectedService] = useState<ServiceItem | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getServices(),
      apiClient.getServicesOverviewStats(),
    ])
      .then(([servicesRes, statsRes]) => {
        if (!mounted) return;
        setServices(servicesRes.data);
        setStats(statsRes.data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!mounted) return;
        const e = err as { message?: string; details?: Record<string, unknown> };
        setError({
          message: e.message || 'Failed to load services registry',
          details: e.details,
        });
        setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  // Filtered & sorted services
  const filteredServices = useMemo(() => {
    return services
      .filter((svc) => {
        const matchesQuery =
          svc.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          svc.identifier.toLowerCase().includes(searchQuery.toLowerCase()) ||
          svc.ownerTeam.toLowerCase().includes(searchQuery.toLowerCase());
        if (!matchesQuery) return false;

        if (selectedTier !== 'all' && svc.tier.toString() !== selectedTier) {
          return false;
        }

        if (selectedStatus !== 'all' && svc.status !== selectedStatus) {
          return false;
        }

        return true;
      })
      .sort((a, b) => {
        let valA = a[sortField];
        let valB = b[sortField];
        if (typeof valA === 'string') {
          return sortOrder === 'asc'
            ? valA.localeCompare(valB as string)
            : (valB as string).localeCompare(valA);
        }
        return sortOrder === 'asc'
          ? (valA as number) - (valB as number)
          : (valB as number) - (valA as number);
      });
  }, [services, searchQuery, selectedTier, selectedStatus, sortField, sortOrder]);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  const healthyCount = services.filter((s) => s.status === 'healthy').length;
  const degradedCount = services.filter((s) => s.status === 'degraded').length;
  const unhealthyCount = services.filter((s) => s.status === 'unhealthy').length;

  if (loading && services.length === 0) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <LoadingSpinner message="Fetching monitored microservices and topology catalog..." fullScreen />
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <ErrorState
          title="Service Registry Error"
          message={error.message}
          details={error.details}
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  return (
    <div className="w-full px-margin-desktop py-margin-desktop space-y-space-xl">
      {/* Page Header */}
      <PageHeader
        category="Registry // Inventory"
        categoryIcon="dns"
        title="Services"
        titleBadge={
          <span className="font-mono-caption text-mono-caption text-primary font-medium px-2 py-0.5 rounded-full bg-primary-fixed">
            Auto-synced
          </span>
        }
        subtitle="Catalog of monitored microservices, runtime health, telemetry rates, and dependencies."
        actions={
          <>
            <Button
              variant="surface"
              icon="download"
              onClick={() => alert('Exporting OpenTelemetry service registry JSON schema...')}
            >
              Export Schema
            </Button>
            <Button
              variant="primary"
              icon="add_circle"
              onClick={() => alert('Service registration requires cluster operator approval.')}
            >
              Register New Service
            </Button>
          </>
        }
      />

      {/* 5-Card Health Distribution Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-space-md">
        {/* Total Services */}
        <div className="flex flex-col p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-secondary mb-1">
            <span className="font-caption-ui text-caption-ui uppercase tracking-wider font-semibold">
              Total Services
            </span>
            <span className="material-symbols-outlined text-[18px] text-primary">hub</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface">
              {stats?.totalServices ?? services.length}
            </span>
            <span className="font-mono-badge text-mono-badge px-1 py-0.5 rounded bg-surface-container text-secondary">
              100% scope
            </span>
          </div>
          <div className="w-full bg-surface-container rounded-full h-1.5 mt-3 overflow-hidden flex">
            <div className="bg-primary h-full" style={{ width: '85.7%' }} />
            <div className="bg-secondary h-full" style={{ width: '10.7%' }} />
            <div className="bg-error h-full" style={{ width: '3.6%' }} />
          </div>
        </div>

        {/* Healthy */}
        <div className="flex flex-col p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-secondary mb-1">
            <span className="font-caption-ui text-caption-ui uppercase tracking-wider font-semibold">
              Healthy
            </span>
            <span className="w-2 h-2 rounded-full bg-primary-container" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface">
              {stats?.healthyCount ?? healthyCount}
            </span>
            <span className="font-mono-caption text-mono-caption text-primary font-semibold">
              {Math.round(((stats?.healthyCount ?? healthyCount) / ((stats?.totalServices ?? services.length) || 1)) * 100)}%
            </span>
          </div>
          <span className="font-caption-ui text-caption-ui text-on-surface-variant mt-2">
            Nominal SLO adherence
          </span>
        </div>

        {/* Degraded */}
        <div className="flex flex-col p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-secondary mb-1">
            <span className="font-caption-ui text-caption-ui uppercase tracking-wider font-semibold">
              Degraded
            </span>
            <span className="w-2 h-2 rounded-full bg-secondary" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface">
              {stats?.degradedCount ?? degradedCount}
            </span>
            <span className="font-mono-caption text-mono-caption text-secondary font-semibold">
              {Math.round(((stats?.degradedCount ?? degradedCount) / ((stats?.totalServices ?? services.length) || 1)) * 100)}%
            </span>
          </div>
          <span className="font-caption-ui text-caption-ui text-on-surface-variant mt-2">
            Elevated p95 latency detected
          </span>
        </div>

        {/* Unhealthy */}
        <div className="flex flex-col p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-secondary mb-1">
            <span className="font-caption-ui text-caption-ui uppercase tracking-wider font-semibold">
              Unhealthy
            </span>
            <span className="w-2 h-2 rounded-full bg-error animate-ping" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono-metric-lg text-mono-metric-lg text-error">
              {stats?.unhealthyCount ?? unhealthyCount}
            </span>
            <span className="font-mono-caption text-mono-caption text-error font-semibold">
              {Math.round(((stats?.unhealthyCount ?? unhealthyCount) / ((stats?.totalServices ?? services.length) || 1)) * 100)}%
            </span>
          </div>
          <span className="font-caption-ui text-caption-ui text-error font-medium mt-2">
            Breaching SLA threshold
          </span>
        </div>

        {/* Telemetry Ingestion */}
        <div className="flex flex-col p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-secondary mb-1">
            <span className="font-caption-ui text-caption-ui uppercase tracking-wider font-semibold">
              Telemetry Ingestion
            </span>
            <span className="material-symbols-outlined text-[18px] text-tertiary">speed</span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="font-mono-body text-mono-body font-semibold text-on-surface">
              {stats?.ingestionBandwidth ?? '0.0 samples/s (0 metrics)'}
            </span>
          </div>
          <span className="font-mono-caption text-mono-caption text-on-surface-variant mt-2">
            {stats?.logPayloadDaily ?? '0 persisted logs'}
            {stats?.applicationRequestRateRps != null
              ? ` · App: ${stats.applicationRequestRateRps.toFixed(1)} req/s`
              : ''}
          </span>
        </div>
      </div>

      {/* Controls & Filter Toolbar */}
      <div className="flex flex-col gap-space-sm p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-md">
          {/* Search Field */}
          <div className="relative flex-1 min-w-[260px] max-w-md">
            <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-[18px] text-secondary">
              filter_list
            </span>
            <input
              className="w-full h-8 pl-9 pr-3 rounded-lg bg-surface-container-low text-on-surface font-body-default text-body-default placeholder:text-outline border border-outline-variant/30 focus:outline-none focus:bg-surface-container focus:text-on-surface transition-colors"
              placeholder="Search services by name, tag, tier, or owner..."
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div className="flex flex-wrap items-center gap-space-sm">
            {/* Environment Indicator */}
            <div className="relative inline-flex items-center">
              <span className="font-caption-ui text-caption-ui text-secondary mr-2">Env:</span>
              <div className="flex items-center gap-1.5 px-space-sm py-1 rounded-lg bg-surface-container-low text-on-surface font-body-medium text-body-medium border border-outline-variant/20">
                <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                <span>Production</span>
              </div>
            </div>

            {/* Tier Filter Segmented Control */}
            <div className="flex items-center p-0.5 rounded-lg bg-surface-container-low font-caption-ui text-caption-ui border border-outline-variant/20">
              {(
                [
                  { id: 'all', label: 'All Tiers' },
                  { id: '0', label: 'Tier 0 (Core)' },
                  { id: '1', label: 'Tier 1' },
                  { id: '2', label: 'Tier 2' },
                ] as const
              ).map((tier) => (
                <button
                  key={tier.id}
                  type="button"
                  onClick={() => setSelectedTier(tier.id)}
                  className={`px-2.5 py-1 rounded transition-all font-medium ${
                    selectedTier === tier.id
                      ? 'text-on-surface bg-surface-container-lowest shadow-sm font-semibold'
                      : 'text-secondary hover:text-on-surface'
                  }`}
                >
                  {tier.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Health Status Filter Pills */}
        <div className="flex flex-wrap items-center gap-space-xs pt-space-xs border-t border-outline-variant/15">
          <span className="font-caption-ui text-caption-ui text-secondary mr-1">Status:</span>

          <button
            type="button"
            onClick={() => setSelectedStatus('all')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-caption-ui text-caption-ui transition-colors ${
              selectedStatus === 'all'
                ? 'bg-primary text-on-primary'
                : 'bg-surface-container-low hover:bg-surface-container text-on-surface'
            }`}
          >
            <span>All Services</span>
            <span
              className={`font-mono-badge text-mono-badge px-1 rounded-full ${
                selectedStatus === 'all' ? 'bg-on-primary/20' : 'bg-surface-container text-secondary'
              }`}
            >
              {services.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setSelectedStatus('healthy')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-caption-ui text-caption-ui transition-colors ${
              selectedStatus === 'healthy'
                ? 'bg-primary text-on-primary'
                : 'bg-surface-container-low hover:bg-surface-container text-on-surface'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-primary-container" />
            <span>Healthy</span>
            <span
              className={`font-mono-badge text-mono-badge px-1 rounded-full ${
                selectedStatus === 'healthy' ? 'bg-on-primary/20' : 'bg-surface-container text-secondary'
              }`}
            >
              {healthyCount}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setSelectedStatus('degraded')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-caption-ui text-caption-ui transition-colors ${
              selectedStatus === 'degraded'
                ? 'bg-tertiary text-on-tertiary'
                : 'bg-surface-container-low hover:bg-surface-container text-on-surface'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
            <span>Degraded</span>
            <span
              className={`font-mono-badge text-mono-badge px-1 rounded-full ${
                selectedStatus === 'degraded' ? 'bg-on-tertiary/20' : 'bg-secondary/15 text-secondary'
              }`}
            >
              {degradedCount}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setSelectedStatus('unhealthy')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-caption-ui text-caption-ui transition-colors ${
              selectedStatus === 'unhealthy'
                ? 'bg-error text-on-error'
                : 'bg-surface-container-low hover:bg-surface-container text-on-surface'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-error" />
            <span>Unhealthy</span>
            <span
              className={`font-mono-badge text-mono-badge px-1 rounded-full font-bold ${
                selectedStatus === 'unhealthy' ? 'bg-on-error/20' : 'bg-error-container text-on-error-container'
              }`}
            >
              {unhealthyCount}
            </span>
          </button>
        </div>
      </div>

      {/* Services Table */}
      <div className="flex flex-col rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-low text-secondary font-caption-ui text-caption-ui uppercase tracking-wider h-10 select-none border-b border-outline-variant/20">
                <th
                  className="py-2 px-space-md font-semibold cursor-pointer hover:text-on-surface"
                  onClick={() => toggleSort('name')}
                >
                  <div className="flex items-center gap-1">
                    <span>Service Name &amp; Tier</span>
                    {sortField === 'name' && (
                      <span className="material-symbols-outlined text-[14px]">
                        {sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'}
                      </span>
                    )}
                  </div>
                </th>
                <th className="py-2 px-space-md font-semibold">Owner Team</th>
                <th className="py-2 px-space-md font-semibold">Environment</th>
                <th className="py-2 px-space-md font-semibold">Health Status</th>
                <th
                  className="py-2 px-space-md font-semibold text-right cursor-pointer hover:text-on-surface"
                  onClick={() => toggleSort('requestRateRps')}
                >
                  <div className="flex items-center justify-end gap-1">
                    <span>Request Rate</span>
                    {sortField === 'requestRateRps' && (
                      <span className="material-symbols-outlined text-[14px]">
                        {sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'}
                      </span>
                    )}
                  </div>
                </th>
                <th
                  className="py-2 px-space-md font-semibold text-right cursor-pointer hover:text-on-surface"
                  onClick={() => toggleSort('errorRatePercent')}
                >
                  <div className="flex items-center justify-end gap-1">
                    <span>Error Rate</span>
                    {sortField === 'errorRatePercent' && (
                      <span className="material-symbols-outlined text-[14px]">
                        {sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'}
                      </span>
                    )}
                  </div>
                </th>
                <th
                  className="py-2 px-space-md font-semibold text-right cursor-pointer hover:text-on-surface"
                  onClick={() => toggleSort('p95LatencyMs')}
                >
                  <div className="flex items-center justify-end gap-1">
                    <span>P95 Latency</span>
                    {sortField === 'p95LatencyMs' && (
                      <span className="material-symbols-outlined text-[14px]">
                        {sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'}
                      </span>
                    )}
                  </div>
                </th>
                <th className="py-2 px-space-md font-semibold text-center w-36">
                  Signals Sparkline (15m)
                </th>
                <th className="py-2 px-space-md font-semibold text-right">Last Seen</th>
                <th className="py-2 px-space-md font-semibold text-center w-24">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container font-body-default text-body-default text-on-surface">
              {filteredServices.map((svc) => (
                <tr
                  key={svc.id}
                  onClick={() => setSelectedService(svc)}
                  className={`group transition-colors cursor-pointer ${
                    selectedService?.id === svc.id
                      ? 'bg-primary-fixed/20'
                      : svc.status === 'unhealthy'
                      ? 'bg-error-container/10 hover:bg-error-container/20'
                      : svc.status === 'degraded'
                      ? 'bg-surface-container-low/40 hover:bg-surface-container-low'
                      : 'bg-surface-container-lowest hover:bg-surface-container-low'
                  }`}
                >
                  <td className="py-3 px-space-md">
                    <div className="flex items-center gap-space-sm">
                      <div
                        className={`w-8 h-8 rounded-lg flex items-center justify-center transition-colors ${
                          svc.status === 'unhealthy'
                            ? 'bg-error-container text-on-error-container'
                            : svc.status === 'degraded'
                            ? 'bg-secondary-container/40 text-on-secondary-fixed'
                            : 'bg-surface-container text-primary'
                        }`}
                      >
                        <span className="material-symbols-outlined text-[18px]">
                          {svc.identifier.startsWith('db:')
                            ? 'database'
                            : svc.name.includes('Order')
                            ? 'shopping_cart'
                            : svc.name.includes('Payment')
                            ? 'credit_card'
                            : svc.name.includes('User')
                            ? 'person'
                            : svc.name.includes('Notification')
                            ? 'forward_to_inbox'
                            : 'dns'}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <div className="flex items-center gap-1.5">
                          <span className="font-body-medium text-body-medium text-on-surface font-semibold group-hover:text-primary transition-colors">
                            {svc.name}
                          </span>
                          <span className="font-mono-badge text-mono-badge px-1 py-0.2 rounded bg-primary-fixed text-on-primary-fixed-variant font-medium">
                            Tier {svc.tier}
                          </span>
                        </div>
                        <span className="font-mono-caption text-mono-caption text-secondary">
                          {svc.identifier}
                        </span>
                      </div>
                    </div>
                  </td>

                  <td className="py-3 px-space-md font-caption-ui text-caption-ui text-secondary">
                    {svc.ownerTeam}
                  </td>

                  <td className="py-3 px-space-md">
                    <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant">
                      {svc.environment}
                    </span>
                  </td>

                  <td className="py-3 px-space-md">
                    {svc.status === 'healthy' && (
                      <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-surface-container-low text-primary font-caption-ui text-caption-ui border border-primary/20">
                        <span className="w-1.5 h-1.5 rounded-full bg-primary-container" />
                        <span className="font-medium">Healthy</span>
                      </div>
                    )}
                    {svc.status === 'degraded' && (
                      <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-secondary-container/40 text-on-secondary-fixed font-caption-ui text-caption-ui border border-secondary/30">
                        <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
                        <span className="font-semibold">Degraded</span>
                      </div>
                    )}
                    {svc.status === 'unhealthy' && (
                      <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-error-container text-on-error-container font-caption-ui text-caption-ui border border-error/30">
                        <span className="w-1.5 h-1.5 rounded-full bg-error animate-ping" />
                        <span className="font-bold">Unhealthy</span>
                      </div>
                    )}
                  </td>

                  <td className="py-3 px-space-md text-right font-mono-body text-mono-body font-medium text-on-surface">
                    {svc.requestRateRps >= 1000
                      ? `${(svc.requestRateRps / 1000).toFixed(1)}k`
                      : svc.requestRateRps}{' '}
                    {svc.identifier.startsWith('db:') ? 'qps' : 'rps'}
                  </td>

                  <td
                    className={`py-3 px-space-md text-right font-mono-body text-mono-body ${
                      svc.status === 'unhealthy'
                        ? 'text-error font-bold'
                        : svc.status === 'degraded'
                        ? 'text-error font-medium'
                        : 'text-primary'
                    }`}
                  >
                    {svc.errorRatePercent.toFixed(2)}%
                  </td>

                  <td
                    className={`py-3 px-space-md text-right font-mono-body text-mono-body ${
                      svc.p95LatencyMs > 1000
                        ? 'text-error font-bold'
                        : svc.p95LatencyMs > 200
                        ? 'text-tertiary font-semibold'
                        : 'text-on-surface'
                    }`}
                  >
                    {svc.p95LatencyMs} ms
                  </td>

                  {/* Signals Sparkline (15m) */}
                  <td className="py-3 px-space-md text-center">
                    <svg
                      className={`w-28 h-6 mx-auto fill-transparent overflow-visible ${
                        svc.status === 'unhealthy'
                          ? 'stroke-error'
                          : svc.status === 'degraded'
                          ? 'stroke-secondary'
                          : 'stroke-primary'
                      }`}
                      viewBox="0 0 100 24"
                    >
                      {svc.status === 'unhealthy' ? (
                        <path
                          d="M0,18 L20,17 L35,16 L45,19 L55,4 L65,22 L75,2 L85,19 L100,1"
                          strokeLinecap="round"
                          strokeWidth="2"
                        />
                      ) : svc.status === 'degraded' ? (
                        <path
                          d="M0,19 L20,18 L35,15 L50,19 L65,8 L80,12 L100,5"
                          strokeLinecap="round"
                          strokeWidth="1.75"
                        />
                      ) : (
                        <path
                          d="M0,18 Q15,17 30,16 T60,15 T85,16 L100,15"
                          strokeLinecap="round"
                          strokeWidth="1.75"
                        />
                      )}
                    </svg>
                  </td>

                  <td className="py-3 px-space-md text-right font-mono-caption text-mono-caption text-secondary">
                    {svc.lastSeen}
                  </td>

                  {/* Actions */}
                  <td className="py-3 px-space-md text-center" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-center gap-1 opacity-60 group-hover:opacity-100 transition-opacity">
                      <button
                        className="p-1 rounded hover:bg-surface-container text-secondary hover:text-primary transition-colors"
                        title="View Traces"
                        type="button"
                        onClick={() => navigate('/traces')}
                      >
                        <span className="material-symbols-outlined text-[16px]">insights</span>
                      </button>
                      <button
                        className="p-1 rounded hover:bg-surface-container text-secondary hover:text-primary transition-colors"
                        title="Live Logs"
                        type="button"
                        onClick={() => navigate('/logs')}
                      >
                        <span className="material-symbols-outlined text-[16px]">terminal</span>
                      </button>
                      <button
                        className="p-1 rounded hover:bg-surface-container text-secondary hover:text-primary transition-colors"
                        title="Dependency Graph"
                        type="button"
                        onClick={() => navigate('/dependency-map')}
                      >
                        <span className="material-symbols-outlined text-[16px]">hub</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Table Footer */}
        <div className="flex flex-col sm:flex-row items-center justify-between p-space-md bg-surface-container-low gap-space-sm text-secondary font-caption-ui text-caption-ui border-t border-outline-variant/20">
          <div className="flex items-center gap-space-xs">
            <span>
              Showing <strong className="text-on-surface">{filteredServices.length}</strong> of{' '}
              <strong className="text-on-surface">{services.length}</strong> registered services
            </span>
          </div>
          <div className="flex items-center gap-space-md">
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-primary-container" />
              <span>SLO Target &gt; 99.9%</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-secondary" />
              <span>Warning &gt; 1%</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-error" />
              <span>Critical &gt; 5%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Slide-out Service Inspector Drawer (when a row is selected) */}
      {selectedService && (
        <div className="p-space-lg rounded-xl bg-surface-container-lowest border-2 border-primary/30 shadow-md flex flex-col gap-space-md animate-in fade-in duration-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-space-sm">
              <div className="w-10 h-10 rounded-lg bg-primary-fixed flex items-center justify-center text-primary font-bold">
                <span className="material-symbols-outlined text-[22px]">dns</span>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                    {selectedService.name}
                  </h3>
                  <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-medium">
                    Tier {selectedService.tier}
                  </span>
                  <span
                    className={`font-mono-badge text-mono-badge px-2 py-0.5 rounded uppercase font-bold ${
                      selectedService.status === 'healthy'
                        ? 'bg-secondary-container text-on-secondary-fixed'
                        : selectedService.status === 'degraded'
                        ? 'bg-tertiary-fixed text-on-tertiary-fixed-variant'
                        : 'bg-error-container text-on-error-container'
                    }`}
                  >
                    {selectedService.status}
                  </span>
                </div>
                <p className="font-mono-caption text-mono-caption text-secondary mt-0.5">
                  {selectedService.identifier} • Owned by {selectedService.ownerTeam}
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => setSelectedService(null)}
              className="p-1 rounded-lg hover:bg-surface-container text-secondary hover:text-on-surface transition-colors"
            >
              <span className="material-symbols-outlined text-[20px]">close</span>
            </button>
          </div>

          <p className="font-body-default text-body-default text-on-surface-variant">
            {selectedService.description ||
              'Microservice instance participating in distributed tracing across the ingress mesh.'}
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-space-sm pt-space-xs">
            <div className="p-space-sm rounded-lg bg-surface-container-low border border-outline-variant/20">
              <span className="font-caption-ui text-caption-ui text-secondary block">Availability SLO</span>
              <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
                {selectedService.availabilityPercent !== undefined ? `${selectedService.availabilityPercent}%` : 'N/A'}
              </span>
            </div>

            <div className="p-space-sm rounded-lg bg-surface-container-low border border-outline-variant/20">
              <span className="font-caption-ui text-caption-ui text-secondary block">CPU Saturation</span>
              <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
                {selectedService.cpuSaturationPercent !== undefined ? `${selectedService.cpuSaturationPercent}%` : 'N/A'}
              </span>
            </div>

            <div className="p-space-sm rounded-lg bg-surface-container-low border border-outline-variant/20">
              <span className="font-caption-ui text-caption-ui text-secondary block">Memory Usage</span>
              <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
                {selectedService.memoryUsagePercent !== undefined ? `${selectedService.memoryUsagePercent}%` : 'N/A'}
              </span>
            </div>

            <div className="p-space-sm rounded-lg bg-surface-container-low border border-outline-variant/20">
              <span className="font-caption-ui text-caption-ui text-secondary block">Last Deployment</span>
              <span className="font-mono-caption text-mono-caption text-on-surface font-medium block mt-1">
                {selectedService.lastDeployment ?? 'N/A'}
              </span>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-space-md pt-space-xs">
            <div className="flex-1">
              <span className="font-caption-ui text-caption-ui text-secondary uppercase tracking-wider font-semibold block mb-1.5">
                Upstream Callers
              </span>
              <div className="flex flex-wrap gap-1.5">
                {selectedService.upstreamDependencies && selectedService.upstreamDependencies.length > 0 ? (
                  selectedService.upstreamDependencies.map((dep) => (
                    <span
                      key={dep}
                      className="px-2 py-0.5 rounded bg-surface-container text-on-surface font-mono-caption text-mono-caption border border-outline-variant/30"
                    >
                      {dep}
                    </span>
                  ))
                ) : (
                  <span className="text-outline text-caption-ui">None (Entrypoint)</span>
                )}
              </div>
            </div>

            <div className="flex-1">
              <span className="font-caption-ui text-caption-ui text-secondary uppercase tracking-wider font-semibold block mb-1.5">
                Downstream Dependencies
              </span>
              <div className="flex flex-wrap gap-1.5">
                {selectedService.downstreamDependencies && selectedService.downstreamDependencies.length > 0 ? (
                  selectedService.downstreamDependencies.map((dep) => (
                    <span
                      key={dep}
                      className="px-2 py-0.5 rounded bg-surface-container text-on-surface font-mono-caption text-mono-caption border border-outline-variant/30"
                    >
                      {dep}
                    </span>
                  ))
                ) : (
                  <span className="text-outline text-caption-ui">None (Leaf Node)</span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-space-sm pt-space-sm border-t border-outline-variant/20">
            <Button variant="surface" icon="hub" onClick={() => navigate('/dependency-map')}>
              Locate in Dependency Map
            </Button>
            <Button variant="secondary" icon="insights" onClick={() => navigate('/traces')}>
              Inspect Live Traces
            </Button>
            <Button
              variant="primary"
              icon="crisis_alert"
              onClick={() => navigate('/incidents')}
            >
              Correlate Incidents
            </Button>
          </div>
        </div>
      )}

      {/* Architectural Insights Bento Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-space-md">
        {/* Active Critical Bottleneck */}
        <div className="flex flex-col p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm gap-space-sm">
          <div className="flex items-center justify-between">
            <span className="font-title-md text-title-md text-on-surface font-semibold">
              Active Critical Bottleneck
            </span>
            <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-error-container text-on-error-container font-semibold">
              P0 IMPACT
            </span>
          </div>
          <p className="font-body-default text-body-default text-on-surface-variant">
            Database lock contention on{' '}
            <span className="font-mono-caption text-mono-caption font-semibold text-error">
              db:aurora-cluster-leader
            </span>{' '}
            is cascading into Degraded responses in Checkout Core and Payment Engine.
          </p>
          <div className="flex items-center gap-space-sm p-space-sm rounded-lg bg-surface-container-low mt-auto border border-outline-variant/20">
            <span className="material-symbols-outlined text-[20px] text-primary">auto_awesome</span>
            <div className="flex flex-col">
              <span className="font-caption-ui text-caption-ui font-semibold text-on-surface flex items-center gap-1.5">
                AI Root Cause Suggestion
                <span className="font-mono-badge text-mono-badge px-1 py-0.2 rounded bg-surface-container text-outline font-normal">
                  Simulated Demo
                </span>
              </span>
              <span className="font-mono-caption text-mono-caption text-secondary">
                Heavy read transaction holds table locks on `orders_v2` index build.
              </span>
            </div>
          </div>
        </div>

        {/* Telemetry Pipeline Load */}
        <div className="flex flex-col p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm gap-space-sm">
          <div className="flex items-center justify-between">
            <span className="font-title-md text-title-md text-on-surface font-semibold">
              Telemetry Pipeline Load
            </span>
            <span className="font-mono-caption text-mono-caption text-primary font-medium">
              OTel Collector: OK
            </span>
          </div>
          <div className="flex items-center justify-between text-secondary font-caption-ui text-caption-ui">
            <span>Collector Buffer Pool</span>
            <span className="font-mono-body text-mono-body text-on-surface font-semibold">24% utilized</span>
          </div>
          <div className="w-full bg-surface-container rounded-full h-1.5 overflow-hidden">
            <div className="bg-primary h-full rounded-full" style={{ width: '24%' }} />
          </div>
          <div className="flex items-center justify-between text-secondary font-caption-ui text-caption-ui mt-2">
            <span>Dead Letter Queue Drop Rate</span>
            <span className="font-mono-body text-mono-body text-primary font-semibold">0.00%</span>
          </div>
          <div className="w-full bg-surface-container rounded-full h-1.5 overflow-hidden">
            <div className="bg-primary h-full rounded-full" style={{ width: '0%' }} />
          </div>
          <span className="font-mono-caption text-mono-caption text-secondary mt-auto">
            Sampling rule: 100% errors, 10% nominal 2xx traffic.
          </span>
        </div>

        {/* Quick Registry Actions & Runbooks */}
        <div className="flex flex-col p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm justify-between">
          <div className="flex flex-col gap-space-xs">
            <span className="font-title-md text-title-md text-on-surface font-semibold">
              Service Registry Actions
            </span>
            <p className="font-body-default text-body-default text-on-surface-variant">
              Quickly trigger distributed diagnostics or launch automated runbooks against the registered topology.
            </p>
          </div>
          <div className="flex flex-col gap-space-xs mt-space-md">
            <button
              className="w-full flex items-center justify-between px-space-md py-2 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface transition-colors cursor-pointer"
              type="button"
              onClick={() => navigate('/dependency-map')}
            >
              <span className="flex items-center gap-2 font-body-medium text-body-medium">
                <span className="material-symbols-outlined text-[18px] text-primary">account_tree</span>
                Open Multi-Tier Dependency Graph
              </span>
              <span className="material-symbols-outlined text-[16px] text-secondary">arrow_forward</span>
            </button>
            <button
              className="w-full flex items-center justify-between px-space-md py-2 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface transition-colors cursor-pointer"
              type="button"
              onClick={() => alert('Downloading OpenTelemetry agent configuration file (otel-collector-config.yaml)...')}
            >
              <span className="flex items-center gap-2 font-body-medium text-body-medium">
                <span className="material-symbols-outlined text-[18px] text-secondary">terminal</span>
                Download OpenTelemetry Agent Config
              </span>
              <span className="material-symbols-outlined text-[16px] text-secondary">arrow_forward</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
