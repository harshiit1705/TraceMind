import React, { useEffect, useState } from 'react';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { TraceItem } from '../../types';

export const TraceExplorerPage: React.FC = () => {
  const [traces, setTraces] = useState<TraceItem[]>([]);

  useEffect(() => {
    let mounted = true;
    apiClient.getTraces()
      .then((res) => {
        if (mounted) setTraces(res.data);
      })
      .catch(() => {});
    return () => { mounted = false; };
  }, []);

  return (
    <div className="w-full px-margin-desktop py-margin-desktop">
      <div className="flex flex-col w-full gap-space-lg">
        {/* Header */}
        <PageHeader
          category="Trace Analytics"
          categoryIcon="route"
          categoryBadge={
            <div className="flex items-center gap-2">
              <span className="font-caption-ui text-caption-ui text-on-surface-variant">Showing</span>
              <span className="font-mono-metric-lg text-title-md text-on-surface">1,420</span>
              <span className="font-caption-ui text-caption-ui text-outline">traces evaluated</span>
              <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-error-container text-on-error-container font-mono-badge text-mono-badge">
                <span className="w-1.5 h-1.5 rounded-full bg-error animate-pulse" />
                <span>42 anomalous (2.95%)</span>
              </span>
            </div>
          }
          title="Trace Explorer"
          subtitle="Explore distributed trace waterfalls, service latency propagation, and call hierarchy."
          actions={
            <>
              <Button variant="secondary" icon="tune">Live Tail: Active</Button>
              <Button variant="secondary" icon="download">Export OTel JSON</Button>
              <Button variant="primary" icon="play_arrow">Run Query</Button>
            </>
          }
        />

        {/* Monospace Query Terminal Mock */}
        <div className="bg-surface-container-lowest p-space-md rounded-xl shadow-sm border border-outline-variant/30 flex flex-col gap-space-sm">
          <div className="relative w-full flex items-center bg-surface-container-low rounded-lg p-1 shadow-inner">
            <span className="font-mono-badge text-mono-badge px-2 py-1 rounded bg-surface-container-highest text-primary font-semibold tracking-wide ml-1">
              KQL/TRACE
            </span>
            <input
              type="text"
              readOnly
              value="service:api-gateway AND status:error AND duration:>500ms AND trace_id:tr-9f82d4e7a1b0c*"
              className="w-full bg-transparent px-3 py-1.5 font-mono-body text-mono-body text-on-surface focus:outline-none"
            />
            <button className="px-2.5 py-1 rounded bg-surface-container text-on-surface-variant font-mono-caption text-mono-caption hover:bg-surface-container-high transition-colors">
              Saved (4)
            </button>
          </div>
        </div>

        {/* Trace List Preview */}
        <div className="bg-surface-container-lowest rounded-xl shadow-sm border border-outline-variant/30 p-space-md flex flex-col gap-space-sm">
          <div className="flex items-center justify-between pb-space-xs border-b border-outline-variant/20">
            <span className="font-caption-ui text-caption-ui uppercase font-semibold text-outline tracking-wider">
              Indexed Traces ({traces.length} loaded)
            </span>
            <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant font-medium">
              SORT: LATENCY DESC
            </span>
          </div>

          <div className="flex flex-col divide-y divide-outline-variant/20">
            {traces.map((trace) => (
              <div key={trace.id} className="py-2.5 flex items-center justify-between gap-space-md hover:bg-surface-container-low transition-colors px-2 rounded-lg">
                <div className="flex items-center gap-space-sm">
                  <span className={`w-1.5 h-5 rounded-full ${trace.anomalous ? 'bg-error' : 'bg-primary'}`} />
                  <span className="font-mono-body text-mono-body font-semibold text-primary">{trace.id}</span>
                  <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface">
                    {trace.rootService}
                  </span>
                  <span className="font-mono-body text-mono-body text-on-surface text-[12px] truncate max-w-md">
                    {trace.rootEndpoint}
                  </span>
                </div>
                <div className="flex items-center gap-space-md">
                  <span className={`font-mono-body text-mono-body font-semibold ${trace.anomalous ? 'text-error' : 'text-on-surface'}`}>
                    {trace.durationMs}ms
                  </span>
                  <span className="font-mono-caption text-mono-caption text-outline">{trace.spansCount} spans</span>
                  <span className={`font-mono-badge text-mono-badge px-2 py-0.5 rounded-full font-semibold ${
                    trace.anomalous ? 'bg-error-container text-on-error-container' : 'bg-surface-container text-on-surface-variant'
                  }`}>
                    {trace.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Phase 2.1 Waterfall Scaffold Notice */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30">
          <h3 className="font-title-md text-title-md text-on-surface font-semibold mb-1">
            Gantt Waterfall Flamegraph Visualizer Ready for Phase 2.4
          </h3>
          <p className="font-body-default text-body-default text-on-surface-variant">
            Interactive timing rulers, span hierarchical trees, nested execution bars, error stack payload drawers, and span attribute inspectors are scoped for Phase 2.4.
          </p>
        </div>
      </div>
    </div>
  );
};

