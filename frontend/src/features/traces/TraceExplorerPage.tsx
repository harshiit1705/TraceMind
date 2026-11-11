import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { ServiceItem, SpanItem, TraceItem } from '../../types';

export const TraceExplorerPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [traces, setTraces] = useState<TraceItem[]>([]);
  const [totalTraces, setTotalTraces] = useState<number>(0);
  const [services, setServices] = useState<ServiceItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<{ message: string; details?: Record<string, unknown> } | null>(null);

  const [selectedService, setSelectedService] = useState<string>(searchParams.get('service') || '');
  const [selectedStatus, setSelectedStatus] = useState<string>(searchParams.get('status') || '');
  const [minDuration, setMinDuration] = useState<string>(searchParams.get('min_duration_ms') || '');
  const [traceIdFilter, setTraceIdFilter] = useState<string>(searchParams.get('trace_id') || '');

  const [selectedTrace, setSelectedTrace] = useState<TraceItem | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [selectedSpan, setSelectedSpan] = useState<SpanItem | null>(null);

  useEffect(() => {
    apiClient
      .getServices()
      .then((res) => setServices(res.data || []))
      .catch(() => {
        /* non-blocking service list fallback */
      });
  }, []);

  const loadTraceDetail = useCallback(async (traceId: string) => {
    setDetailLoading(true);
    setSelectedSpan(null);
    try {
      const res = await apiClient.getTraceById(traceId);
      setSelectedTrace(res.data);
      if (res.data?.spans && res.data.spans.length > 0) {
        const bottleneck = res.data.spans.find((s) => s.isBottleneck);
        setSelectedSpan(bottleneck || res.data.spans[0]);
      }
    } catch {
      /* retain existing trace list state */
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const fetchTraces = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const minMs = minDuration.trim() ? Number(minDuration) : undefined;
      const res = await apiClient.getTracesPaginated({
        service: selectedService || undefined,
        status: selectedStatus || undefined,
        minDurationMs: minMs !== undefined && !Number.isNaN(minMs) ? minMs : undefined,
        traceId: traceIdFilter.trim() || undefined,
        limit: 30,
      });
      const loadedItems = res.data.items || [];
      setTraces(loadedItems);
      setTotalTraces(res.data.total ?? loadedItems.length);
      setLoading(false);

      if (traceIdFilter.trim() && loadedItems.length > 0) {
        loadTraceDetail(loadedItems[0].id);
      } else if (loadedItems.length > 0 && !selectedTrace) {
        loadTraceDetail(loadedItems[0].id);
      }
    } catch (err: unknown) {
      const e = err as { message?: string; details?: Record<string, unknown> };
      setError({
        message: e.message || 'Failed to load trace spans',
        details: e.details,
      });
      setLoading(false);
    }
  }, [selectedService, selectedStatus, minDuration, traceIdFilter, loadTraceDetail]);

  useEffect(() => {
    fetchTraces();
  }, [fetchTraces]);

  const updateUrlParams = (svc: string, st: string, minMs: string, tid: string) => {
    const next = new URLSearchParams();
    if (svc) next.set('service', svc);
    if (st) next.set('status', st);
    if (minMs.trim()) next.set('min_duration_ms', minMs.trim());
    if (tid.trim()) next.set('trace_id', tid.trim());
    setSearchParams(next, { replace: true });
  };

  const anomalousCount = traces.filter((t) => t.anomalous).length;

  return (
    <div className="w-full px-margin-desktop py-margin-desktop space-y-space-lg">
      <PageHeader
        category="Telemetry // Traces"
        categoryIcon="account_tree"
        title="Trace Explorer"
        categoryBadge={
          <div className="flex items-center gap-1 font-mono-caption text-mono-caption text-on-surface-variant bg-surface-container px-2 py-0.5 rounded">
            <span>{totalTraces} traces</span>
            <span>·</span>
            <span className={anomalousCount > 0 ? 'text-error font-semibold' : 'text-on-surface-variant'}>
              {anomalousCount} anomalous
            </span>
          </div>
        }
        subtitle="Inspect end-to-end distributed request waterfalls, downstream latency bottlenecks, and parent-child span hierarchies."
        actions={
          <Button variant="surface" icon="refresh" onClick={fetchTraces}>
            Refresh
          </Button>
        }
      />

      {/* Filter Bar */}
      <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm grid grid-cols-1 md:grid-cols-4 gap-space-sm">
        <div className="flex flex-col gap-1">
          <label className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
            Participating Service
          </label>
          <select
            value={selectedService}
            onChange={(e) => {
              setSelectedService(e.target.value);
              updateUrlParams(e.target.value, selectedStatus, minDuration, traceIdFilter);
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
            Span Status
          </label>
          <select
            value={selectedStatus}
            onChange={(e) => {
              setSelectedStatus(e.target.value);
              updateUrlParams(selectedService, e.target.value, minDuration, traceIdFilter);
            }}
            className="h-9 px-2.5 rounded-lg bg-surface-container-low text-on-surface font-body-default text-body-default border border-outline-variant/30 focus:outline-none focus:border-primary"
          >
            <option value="">All Statuses</option>
            <option value="ok">OK Only</option>
            <option value="error">Errors Only</option>
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="font-caption-ui text-caption-ui text-secondary uppercase font-semibold">
            Min Duration (ms)
          </label>
          <input
            type="number"
            min="0"
            value={minDuration}
            onChange={(e) => {
              setMinDuration(e.target.value);
              updateUrlParams(selectedService, selectedStatus, e.target.value, traceIdFilter);
            }}
            placeholder="e.g. 300"
            className="h-9 px-3 rounded-lg bg-surface-container-low text-on-surface font-mono-caption text-mono-caption border border-outline-variant/30 placeholder:text-outline focus:outline-none focus:border-primary"
          />
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
              updateUrlParams(selectedService, selectedStatus, minDuration, e.target.value);
            }}
            placeholder="Search trace_id prefix..."
            className="h-9 px-3 rounded-lg bg-surface-container-low text-on-surface font-mono-caption text-mono-caption border border-outline-variant/30 placeholder:text-outline focus:outline-none focus:border-primary"
          />
        </div>
      </div>

      {loading ? (
        <LoadingSpinner message="Ingesting recent distributed traces from edge collector..." />
      ) : error ? (
        <ErrorState
          title="Trace Query Error"
          message={error.message}
          details={error.details}
          onRetry={fetchTraces}
        />
      ) : traces.length === 0 ? (
        <div className="p-space-xl rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm text-center space-y-2">
          <span className="material-symbols-outlined text-[36px] text-outline">account_tree</span>
          <h3 className="font-title-md text-title-md text-on-surface font-semibold">
            No distributed traces match filters
          </h3>
          <p className="font-body-default text-body-default text-on-surface-variant max-w-lg mx-auto">
            Run microservice checkout traffic to emit cross-service spans or reset active filters.
          </p>
          {(selectedService || selectedStatus || minDuration || traceIdFilter) && (
            <div className="pt-2">
              <Button
                variant="surface"
                onClick={() => {
                  setSelectedService('');
                  setSelectedStatus('');
                  setMinDuration('');
                  setTraceIdFilter('');
                  updateUrlParams('', '', '', '');
                }}
              >
                Reset Filters
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-space-md">
          {/* Trace List */}
          <div className="flex flex-col rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm overflow-hidden">
            <div className="p-space-md border-b border-outline-variant/20 bg-surface-container-low flex items-center justify-between">
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                Captured Distributed Traces
              </span>
              <span className="font-mono-caption text-mono-caption text-outline">
                Select any trace below to inspect span timing waterfall
              </span>
            </div>

            <div className="divide-y divide-outline-variant/15">
              {traces.map((trace) => {
                const isSelected = selectedTrace?.id === trace.id;
                return (
                  <div
                    key={trace.id}
                    onClick={() => loadTraceDetail(trace.id)}
                    className={`p-space-md flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm transition-colors cursor-pointer ${
                      isSelected ? 'bg-primary-fixed/30' : 'hover:bg-surface-container-low/60'
                    }`}
                  >
                    <div className="flex flex-col gap-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono-caption text-mono-caption text-primary font-semibold truncate max-w-[260px]">
                          {trace.id}
                        </span>
                        <span className="font-title-md text-title-md text-on-surface font-medium">
                          {trace.rootService}
                        </span>
                        <span className="font-mono-caption text-mono-caption px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant">
                          {trace.rootEndpoint}
                        </span>
                      </div>
                      <span className="font-mono-caption text-mono-caption text-outline">
                        {new Date(trace.timestamp).toLocaleString()}
                      </span>
                    </div>

                    <div className="flex items-center gap-space-md shrink-0">
                      <span
                        className={`font-mono-body text-mono-body font-semibold ${
                          trace.anomalous ? 'text-error' : 'text-on-surface'
                        }`}
                      >
                        {Number(trace.durationMs).toFixed(1)}ms
                      </span>
                      <span className="font-mono-caption text-mono-caption text-outline">
                        {trace.spansCount} spans
                      </span>
                      <span
                        className={`font-mono-badge text-mono-badge px-2 py-0.5 rounded-full font-semibold ${
                          trace.anomalous
                            ? 'bg-error-container text-on-error-container'
                            : 'bg-surface-container text-on-surface-variant'
                        }`}
                      >
                        {trace.status}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Interactive Span Waterfall Visualizer */}
          {detailLoading ? (
            <LoadingSpinner message="Building distributed span hierarchy waterfall..." />
          ) : (
            selectedTrace && (
              <div className="rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm overflow-hidden">
                <div className="p-space-md border-b border-outline-variant/20 bg-surface-container-low flex flex-wrap items-center justify-between gap-space-sm">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                        Waterfall: {selectedTrace.rootService} · {selectedTrace.rootEndpoint}
                      </h3>
                      <span className="font-mono-caption text-mono-caption text-primary">
                        {selectedTrace.id}
                      </span>
                    </div>
                    <p className="font-mono-caption text-mono-caption text-on-surface-variant mt-0.5">
                      Total Duration: {Number(selectedTrace.durationMs).toFixed(2)}ms · {selectedTrace.spansCount} spans
                    </p>
                  </div>

                  <Button
                    variant="surface"
                    size="sm"
                    icon="article"
                    onClick={() => navigate(`/logs?trace_id=${encodeURIComponent(selectedTrace.id)}`)}
                  >
                    View Correlated Logs
                  </Button>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 divide-y lg:divide-y-0 lg:divide-x divide-outline-variant/20">
                  {/* Waterfall Timeline Bars */}
                  <div className="lg:col-span-2 divide-y divide-outline-variant/15">
                    {(selectedTrace.spans || []).map((span) => {
                      const depth = span.depth ?? 0;
                      const isActive = selectedSpan?.id === span.id;
                      const barColor =
                        span.status === 'error'
                          ? 'bg-error'
                          : span.isBottleneck
                          ? 'bg-tertiary'
                          : 'bg-primary';
                      return (
                        <div
                          key={span.id}
                          onClick={() => setSelectedSpan(span)}
                          className={`px-space-md py-space-sm cursor-pointer transition-colors grid grid-cols-12 items-center gap-2 ${
                            isActive ? 'bg-primary-fixed/25' : 'hover:bg-surface-container-low/60'
                          }`}
                        >
                          <div
                            className="col-span-6 flex items-center gap-1.5 min-w-0"
                            style={{ paddingLeft: `${Math.min(depth, 6) * 14}px` }}
                          >
                            <span
                              className={`font-mono-badge text-mono-badge px-1 py-0.2 rounded uppercase shrink-0 ${
                                span.span_kind === 'client'
                                  ? 'bg-secondary-container text-on-secondary-fixed'
                                  : span.span_kind === 'internal'
                                  ? 'bg-surface-container-high text-on-surface-variant'
                                  : 'bg-primary-fixed text-primary'
                              }`}
                            >
                              {span.span_kind || 'span'}
                            </span>
                            <div className="min-w-0">
                              <div className="font-body-medium text-body-medium text-on-surface truncate">
                                {span.service}
                              </div>
                              <div className="font-mono-caption text-mono-caption text-outline truncate">
                                {span.operation || span.name}
                              </div>
                            </div>
                          </div>

                          <div className="col-span-4 relative h-5 bg-surface-container rounded overflow-hidden">
                            <div
                              className={`absolute top-1 bottom-1 rounded ${barColor}`}
                              style={{
                                left: `${Math.min(98, span.offsetPercent ?? 0)}%`,
                                width: `${Math.max(2, span.widthPercent ?? 5)}%`,
                              }}
                            />
                          </div>

                          <div className="col-span-2 text-right flex items-center justify-end gap-1">
                            {span.isBottleneck && (
                              <span
                                className="font-mono-badge text-mono-badge px-1 rounded bg-tertiary-fixed text-on-tertiary-fixed-variant font-semibold"
                                title="Slowest span bottleneck"
                              >
                                SLOW
                              </span>
                            )}
                            <span
                              className={`font-mono-caption text-mono-caption font-semibold ${
                                span.status === 'error' ? 'text-error' : 'text-on-surface'
                              }`}
                            >
                              {Number(span.durationMs).toFixed(1)}ms
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Span Attribute Inspector */}
                  <div className="p-space-md bg-surface-container-low/40 space-y-space-sm">
                    <span className="font-caption-ui text-caption-ui uppercase tracking-wider font-semibold text-secondary block">
                      Span Inspector
                    </span>
                    {selectedSpan ? (
                      <div className="space-y-space-sm">
                        <div>
                          <div className="font-title-md text-title-md text-on-surface font-semibold">
                            {selectedSpan.operation || selectedSpan.name}
                          </div>
                          <div className="font-mono-caption text-mono-caption text-on-surface-variant">
                            {selectedSpan.service} ({selectedSpan.service_slug || 'service'}) ·{' '}
                            {Number(selectedSpan.durationMs).toFixed(2)}ms
                          </div>
                        </div>

                        <div className="grid grid-cols-1 gap-1 font-mono-caption text-mono-caption text-on-surface-variant bg-surface-container-lowest p-space-sm rounded-lg border border-outline-variant/20">
                          <div>span_id: {selectedSpan.span_id || selectedSpan.id}</div>
                          <div>parent_span_id: {selectedSpan.parent_span_id || 'root'}</div>
                          <div>status: {selectedSpan.status} {selectedSpan.httpStatus ? `(HTTP ${selectedSpan.httpStatus})` : ''}</div>
                          <div>request_id: {selectedSpan.request_id || '—'}</div>
                        </div>

                        {selectedSpan.exception && (
                          <div className="p-space-sm rounded-lg bg-error-container text-on-error-container font-mono-caption text-mono-caption">
                            <span className="font-semibold">{selectedSpan.exception.type}: </span>
                            {selectedSpan.exception.message}
                          </div>
                        )}

                        <div>
                          <span className="font-caption-ui text-caption-ui uppercase text-secondary font-semibold block mb-1">
                            Attributes
                          </span>
                          <pre className="p-space-sm rounded-lg bg-surface-container text-on-surface font-mono-caption text-mono-caption overflow-x-auto max-h-60">
                            {JSON.stringify(selectedSpan.attributes || {}, null, 2)}
                          </pre>
                        </div>
                      </div>
                    ) : (
                      <p className="font-body-default text-body-default text-on-surface-variant">
                        Select a span row to inspect timing offsets, parent links, and attributes.
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
};
