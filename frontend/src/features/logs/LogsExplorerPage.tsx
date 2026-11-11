import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { ApplicationLogItem, ServiceItem } from '../../types';

const LOG_LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const;

export const LogsExplorerPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [logs, setLogs] = useState<ApplicationLogItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [services, setServices] = useState<ServiceItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<{ message: string; details?: Record<string, unknown> } | null>(null);

  const [selectedService, setSelectedService] = useState<string>(searchParams.get('service') || '');
  const [selectedLevel, setSelectedLevel] = useState<string>(searchParams.get('level') || 'ALL');
  const [traceIdFilter, setTraceIdFilter] = useState<string>(searchParams.get('trace_id') || '');
  const [searchQuery, setSearchQuery] = useState<string>(searchParams.get('search') || '');
  const [offset, setOffset] = useState<number>(0);
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const pageSize = 50;

  useEffect(() => {
    apiClient
      .getServices()
      .then((res) => setServices(res.data || []))
      .catch(() => {
        /* non-blocking service list fallback */
      });
  }, []);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.getLogs({
        service: selectedService || undefined,
        level: selectedLevel !== 'ALL' ? selectedLevel : undefined,
        trace_id: traceIdFilter.trim() || undefined,
        search: searchQuery.trim() || undefined,
        limit: pageSize,
        offset,
      });
      setLogs(res.data.items || []);
      setTotal(res.data.total ?? 0);
      setLoading(false);
    } catch (err: unknown) {
      const e = err as { message?: string; details?: Record<string, unknown> };
      setError({
        message: e.message || 'Failed to load structured application logs',
        details: e.details,
      });
      setLoading(false);
    }
  }, [selectedService, selectedLevel, traceIdFilter, searchQuery, offset]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const applyFilterParams = (svc: string, lvl: string, tid: string, q: string) => {
    const next = new URLSearchParams();
    if (svc) next.set('service', svc);
    if (lvl && lvl !== 'ALL') next.set('level', lvl);
    if (tid.trim()) next.set('trace_id', tid.trim());
    if (q.trim()) next.set('search', q.trim());
    setSearchParams(next, { replace: true });
    setOffset(0);
  };

  const levelBadgeClass = (lvl: string): string => {
    const upper = (lvl || '').toUpperCase();
    if (upper === 'ERROR' || upper === 'CRITICAL') {
      return 'bg-error-container text-on-error-container border border-error/20';
    }
    if (upper === 'WARNING') {
      return 'bg-tertiary-fixed text-on-tertiary-fixed-variant border border-tertiary/20';
    }
    if (upper === 'INFO') {
      return 'bg-secondary-container text-on-secondary-fixed border border-secondary/20';
    }
    return 'bg-surface-container text-on-surface-variant border border-outline-variant/30';
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;

  return (
    <div className="w-full px-margin-desktop py-margin-desktop space-y-space-lg">
      <PageHeader
        category="Telemetry // Logs"
        categoryIcon="article"
        title="Logs Explorer"
        titleBadge={
          <span className="font-mono-caption text-mono-caption text-primary px-2 py-0.5 rounded bg-primary-fixed font-medium">
            {total} {total === 1 ? 'log' : 'logs'}
          </span>
        }
        subtitle="Query structured application logs across monitored services and correlate events by trace or request ID."
        actions={
          <Button variant="surface" icon="refresh" onClick={fetchLogs}>
            Refresh
          </Button>
        }
      />

      {/* Filter Toolbar */}
      <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm space-y-space-sm">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-space-sm">
          <div className="flex flex-col gap-1">
            <label className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              Service
            </label>
            <select
              value={selectedService}
              onChange={(e) => {
                setSelectedService(e.target.value);
                applyFilterParams(e.target.value, selectedLevel, traceIdFilter, searchQuery);
              }}
              className="h-9 px-2.5 rounded-lg bg-surface-container-low text-on-surface font-body-default text-body-default border border-outline-variant/30 focus:outline-none focus:border-primary"
            >
              <option value="">All Services</option>
              {services.map((svc) => (
                <option key={svc.id} value={svc.identifier}>
                  {svc.name} ({svc.identifier})
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              Severity
            </label>
            <select
              value={selectedLevel}
              onChange={(e) => {
                setSelectedLevel(e.target.value);
                applyFilterParams(selectedService, e.target.value, traceIdFilter, searchQuery);
              }}
              className="h-9 px-2.5 rounded-lg bg-surface-container-low text-on-surface font-body-default text-body-default border border-outline-variant/30 focus:outline-none focus:border-primary"
            >
              {LOG_LEVELS.map((lvl) => (
                <option key={lvl} value={lvl}>
                  {lvl === 'ALL' ? 'All Severities' : lvl}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              Trace ID
            </label>
            <input
              type="text"
              value={traceIdFilter}
              onChange={(e) => {
                setTraceIdFilter(e.target.value);
                applyFilterParams(selectedService, selectedLevel, e.target.value, searchQuery);
              }}
              placeholder="Filter by trace_id..."
              className="h-9 px-3 rounded-lg bg-surface-container-low text-on-surface font-mono-caption text-mono-caption border border-outline-variant/30 placeholder:text-outline focus:outline-none focus:border-primary"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
              Message / Exception Search
            </label>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                applyFilterParams(selectedService, selectedLevel, traceIdFilter, e.target.value);
              }}
              placeholder="Search log messages, request_id..."
              className="h-9 px-3 rounded-lg bg-surface-container-low text-on-surface font-body-default text-body-default border border-outline-variant/30 placeholder:text-outline focus:outline-none focus:border-primary"
            />
          </div>
        </div>
      </div>

      {loading ? (
        <LoadingSpinner message="Querying persisted structured application logs..." />
      ) : error ? (
        <ErrorState
          title="Log Query Error"
          message={error.message}
          details={error.details}
          onRetry={fetchLogs}
        />
      ) : logs.length === 0 ? (
        <div className="p-space-xl rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm text-center space-y-2">
          <span className="material-symbols-outlined text-[36px] text-outline">manage_search</span>
          <h3 className="font-title-md text-title-md text-on-surface font-semibold">
            No matching application logs found
          </h3>
          <p className="font-body-default text-body-default text-on-surface-variant max-w-lg mx-auto">
            No persisted logs matched the active filters. Generate microservice traffic in API mode or clear active filters to inspect incoming application events.
          </p>
          {(selectedService || selectedLevel !== 'ALL' || traceIdFilter || searchQuery) && (
            <div className="pt-2">
              <Button
                variant="surface"
                onClick={() => {
                  setSelectedService('');
                  setSelectedLevel('ALL');
                  setTraceIdFilter('');
                  setSearchQuery('');
                  applyFilterParams('', 'ALL', '', '');
                }}
              >
                Clear Filters
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm overflow-hidden">
          <div className="divide-y divide-outline-variant/15">
            {logs.map((entry) => {
              const isExpanded = expandedLogId === entry.id;
              return (
                <div key={entry.id} className="hover:bg-surface-container-low/50 transition-colors">
                  <div
                    onClick={() => setExpandedLogId(isExpanded ? null : entry.id)}
                    className="p-space-md cursor-pointer flex flex-col lg:flex-row lg:items-center justify-between gap-space-sm"
                  >
                    <div className="flex items-start gap-space-sm min-w-0 flex-1">
                      <span
                        className={`font-mono-badge text-mono-badge px-2 py-0.5 rounded uppercase font-semibold shrink-0 mt-0.5 ${levelBadgeClass(
                          entry.level
                        )}`}
                      >
                        {entry.level}
                      </span>

                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono-caption text-mono-caption text-outline">
                            {new Date(entry.timestamp).toLocaleString()}
                          </span>
                          <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-surface-container text-on-surface font-medium">
                            {entry.service_name || entry.service_slug || entry.service_id}
                          </span>
                          {entry.request_id && (
                            <span className="font-mono-caption text-mono-caption text-on-surface-variant">
                              req:{entry.request_id}
                            </span>
                          )}
                          {entry.exception_type && (
                            <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-error/10 text-error font-medium">
                              {entry.exception_type}
                            </span>
                          )}
                        </div>
                        <p className="font-body-default text-body-default text-on-surface break-words">
                          {entry.message}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-space-sm shrink-0">
                      {entry.trace_id && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/traces?trace_id=${encodeURIComponent(entry.trace_id!)}`);
                          }}
                          className="font-mono-caption text-mono-caption px-2 py-1 rounded bg-primary-fixed/60 text-primary hover:bg-primary-fixed transition-colors"
                        >
                          trace:{entry.trace_id.slice(0, 12)}...
                        </button>
                      )}
                      <span className="material-symbols-outlined text-[18px] text-outline">
                        {isExpanded ? 'expand_less' : 'expand_more'}
                      </span>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="px-space-md pb-space-md pt-1 bg-surface-container-low/70 border-t border-outline-variant/15 space-y-2">
                      <div className="flex flex-wrap gap-4 font-mono-caption text-mono-caption text-on-surface-variant">
                        <span>trace_id: {entry.trace_id || '—'}</span>
                        <span>span_id: {entry.span_id || '—'}</span>
                        <span>request_id: {entry.request_id || '—'}</span>
                      </div>
                      {entry.exception_message && (
                        <div className="p-space-sm rounded-lg bg-error-container/40 text-on-error-container font-mono-caption text-mono-caption">
                          <span className="font-semibold">{entry.exception_type || 'Exception'}: </span>
                          {entry.exception_message}
                        </div>
                      )}
                      <div>
                        <span className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold block mb-1">
                          Structured Attributes
                        </span>
                        <pre className="p-space-sm rounded-lg bg-surface-container text-on-surface font-mono-caption text-mono-caption overflow-x-auto">
                          {JSON.stringify(entry.attributes_json || {}, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Pagination Footer */}
          <div className="flex items-center justify-between px-space-md py-space-sm bg-surface-container-low border-t border-outline-variant/20">
            <span className="font-mono-caption text-mono-caption text-on-surface-variant">
              Page {currentPage} of {totalPages} ({total} total logs)
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="surface"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
              >
                Previous
              </Button>
              <Button
                variant="surface"
                size="sm"
                disabled={offset + pageSize >= total}
                onClick={() => setOffset(offset + pageSize)}
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
