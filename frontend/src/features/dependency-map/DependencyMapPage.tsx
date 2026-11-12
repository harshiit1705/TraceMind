import React, { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  MarkerType,
  NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { Button, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { ServiceTopologyData, TopologyNodeData } from '../../types';
import { ServiceNode } from './ServiceNode';

type LayoutMode = 'hierarchical' | 'radial' | 'force';

const nodeTypes: NodeTypes = {
  serviceNode: ServiceNode as any,
};

export const DependencyMapPage: React.FC = () => {
  const navigate = useNavigate();

  const [topology, setTopology] = useState<ServiceTopologyData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<{ message: string; details?: Record<string, unknown> } | null>(null);

  const [layoutMode, setLayoutMode] = useState<LayoutMode>('hierarchical');
  const [anomalousOnly, setAnomalousOnly] = useState<boolean>(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string>('postgres');

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    apiClient
      .getTopology()
      .then((res) => {
        if (!mounted) return;
        setTopology(res.data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!mounted) return;
        const e = err as { message?: string; details?: Record<string, unknown> };
        setError({
          message: e.message || 'Failed to load topology map',
          details: e.details,
        });
        setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  // Compute node coordinates based on layout mode
  const getNodeCoordinates = useCallback(
    (nodeId: string, mode: LayoutMode, tier: number = 1, fallbackIdx: number = 0) => {
      const HIERARCHICAL_POSITIONS: Record<string, { x: number; y: number }> = {
        'api-gateway': { x: 30, y: 240 },
        'user-service': { x: 340, y: 70 },
        'order-service': { x: 340, y: 340 },
        'auth-service': { x: 340, y: 540 },
        'notification-service': { x: 680, y: 70 },
        'inventory-service': { x: 680, y: 220 },
        'payment-service': { x: 680, y: 370 },
        'postgres': { x: 680, y: 550 },
        'stripe-api': { x: 990, y: 280 },
      };

      const RADIAL_POSITIONS: Record<string, { x: number; y: number }> = {
        'postgres': { x: 520, y: 280 },
        'payment-service': { x: 260, y: 160 },
        'inventory-service': { x: 260, y: 280 },
        'order-service': { x: 520, y: 60 },
        'api-gateway': { x: 780, y: 160 },
        'auth-service': { x: 780, y: 280 },
        'user-service': { x: 780, y: 400 },
        'notification-service': { x: 520, y: 500 },
        'stripe-api': { x: 260, y: 400 },
      };

      const FORCE_POSITIONS: Record<string, { x: number; y: number }> = {
        'api-gateway': { x: 60, y: 160 },
        'user-service': { x: 200, y: 440 },
        'auth-service': { x: 200, y: 60 },
        'order-service': { x: 420, y: 180 },
        'notification-service': { x: 640, y: 60 },
        'inventory-service': { x: 640, y: 380 },
        'payment-service': { x: 740, y: 240 },
        'postgres': { x: 500, y: 440 },
        'stripe-api': { x: 960, y: 200 },
      };

      const fallbackPos = { x: 60 + tier * 320, y: 80 + (fallbackIdx % 4) * 150 };
      if (mode === 'radial') return RADIAL_POSITIONS[nodeId] || fallbackPos;
      if (mode === 'force') return FORCE_POSITIONS[nodeId] || fallbackPos;
      return HIERARCHICAL_POSITIONS[nodeId] || fallbackPos;
    },
    []
  );

  // Generate React Flow Nodes
  const nodes: Node[] = useMemo(() => {
    if (!topology) return [];

    let rawNodes = topology.nodes;
    if (anomalousOnly) {
      rawNodes = rawNodes.filter((n) => n.isAnomalous);
    }

    return rawNodes.map((n, idx) => {
      const pos = getNodeCoordinates(n.id, layoutMode, n.tier ?? 1, idx);
      return {
        id: n.id,
        type: 'serviceNode',
        position: pos,
        data: n as Record<string, unknown>,
        selected: n.id === selectedNodeId,
      };
    });
  }, [topology, layoutMode, anomalousOnly, selectedNodeId, getNodeCoordinates]);

  // Generate React Flow Edges
  const edges: Edge[] = useMemo(() => {
    if (!topology) return [];

    const activeNodeIds = new Set(nodes.map((n) => n.id));

    return topology.edges
      .filter((e) => activeNodeIds.has(e.source) && activeNodeIds.has(e.target))
      .map((e) => {
        const isAnomalous = e.isAnomalous;
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          animated: isAnomalous,
          style: {
            stroke: isAnomalous ? '#ba1a1a' : '#3525cd',
            strokeWidth: isAnomalous ? 2.5 : 1.75,
            strokeDasharray: e.protocol === 'Async Event' ? '4 4' : undefined,
          },
          labelStyle: {
            fill: isAnomalous ? '#ba1a1a' : '#464555',
            fontFamily: 'JetBrains Mono',
            fontSize: 10,
            fontWeight: 500,
          },
          labelBgStyle: {
            fill: '#ffffff',
            fillOpacity: 0.9,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isAnomalous ? '#ba1a1a' : '#3525cd',
            width: 14,
            height: 14,
          },
        };
      });
  }, [topology, nodes]);

  // Selected node object for inspector drawer
  const selectedNode: TopologyNodeData | undefined = useMemo(() => {
    if (!topology) return undefined;
    return topology.nodes.find((n) => n.id === selectedNodeId) || topology.nodes[0];
  }, [topology, selectedNodeId]);

  const handleNodeClick = (_event: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  };

  if (loading && !topology) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <LoadingSpinner message="Calculating distributed service topology and dependency edges..." fullScreen />
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <ErrorState
          title="Topology Rendering Error"
          message={error.message}
          details={error.details}
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  return (
    <div className="w-full px-margin-desktop py-margin-desktop space-y-space-md">
      {/* Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-space-md mb-space-xs">
        <div className="flex flex-col">
          <div className="flex items-center gap-space-xs text-primary font-mono-caption text-mono-caption uppercase tracking-wider font-semibold mb-1">
            <span className="material-symbols-outlined text-[14px]">device_hub</span>
            <span>Distributed Topology Graph</span>
            <span className="text-outline">/</span>
            <span className="text-on-surface-variant font-normal">
              Mode: {layoutMode.toUpperCase()}
            </span>
          </div>
          <h1 className="font-headline-md text-headline-md text-on-surface tracking-tight font-semibold">
            Service Dependency Map
          </h1>
          <p className="font-body-default text-body-default text-on-surface-variant mt-0.5">
            Visual topology of distributed microservice communication, synchronous calls, and downstream cascade impact.
          </p>
        </div>

        <div className="flex items-center gap-space-sm flex-wrap">
          {/* Layout Modes */}
          <div className="flex items-center bg-surface-container-low rounded-lg p-0.5 shadow-sm border border-outline-variant/30">
            {(
              [
                { id: 'hierarchical', label: 'Hierarchical', icon: 'account_tree' },
                { id: 'radial', label: 'Radial', icon: 'radar' },
                { id: 'force', label: 'Force-directed', icon: 'bubble_chart' },
              ] as const
            ).map((mode) => (
              <button
                key={mode.id}
                type="button"
                onClick={() => setLayoutMode(mode.id)}
                className={`px-2.5 py-1 rounded font-caption-ui text-caption-ui transition-all flex items-center gap-1 ${
                  layoutMode === mode.id
                    ? 'bg-surface-container-lowest text-primary font-semibold shadow-sm'
                    : 'text-secondary hover:text-on-surface font-medium'
                }`}
              >
                <span className="material-symbols-outlined text-[15px]">{mode.icon}</span>
                <span>{mode.label}</span>
              </button>
            ))}
          </div>

          {/* Anomalous Toggle */}
          <label className="flex items-center gap-2 bg-surface-container-low px-space-sm py-1 rounded-lg cursor-pointer shadow-sm select-none border border-outline-variant/30 hover:bg-surface-container transition-colors">
            <input
              type="checkbox"
              className="w-3.5 h-3.5 accent-primary cursor-pointer rounded"
              checked={anomalousOnly}
              onChange={(e) => setAnomalousOnly(e.target.checked)}
            />
            <span className="font-caption-ui text-caption-ui font-semibold text-on-surface">
              Anomalous Only
            </span>
            <span className="font-mono-badge text-mono-badge px-1 py-0.2 rounded-full bg-error-container text-on-error-container font-medium">
              {topology?.nodes.filter((n) => n.isAnomalous).length ?? 4}
            </span>
          </label>

          {/* Refresh Action */}
          <Button
            variant="primary"
            size="sm"
            icon="refresh"
            onClick={() => {
              setLoading(true);
              apiClient.getTopology().then((r) => {
                setTopology(r.data);
                setLoading(false);
              });
            }}
          >
            Live Recompute
          </Button>
        </div>
      </div>

      {/* Legend & Diagnostic Ribbon */}
      <div className="flex flex-wrap items-center justify-between gap-space-sm bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-space-sm shadow-sm">
        <div className="flex items-center flex-wrap gap-x-space-md gap-y-1">
          <span className="font-mono-caption text-mono-caption text-secondary uppercase tracking-wider font-semibold">
            Topology Legend:
          </span>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-tertiary" />
            <span className="font-caption-ui text-caption-ui text-on-surface">Healthy</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-secondary" />
            <span className="font-caption-ui text-caption-ui text-on-surface">Degraded Latency</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-error opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-error" />
            </span>
            <span className="font-caption-ui text-caption-ui text-error font-semibold">
              Unhealthy / Root Fault
            </span>
          </div>
          <div className="h-3 w-px bg-surface-container-high hidden sm:block" />
          <div className="flex items-center gap-2">
            <svg className="w-6 h-2" viewBox="0 0 24 2">
              <line stroke="#3525cd" strokeWidth="2" x1="0" x2="24" y1="1" y2="1" />
            </svg>
            <span className="font-caption-ui text-caption-ui text-on-surface-variant">Sync HTTP/gRPC</span>
          </div>
          <div className="flex items-center gap-2">
            <svg className="w-6 h-2" viewBox="0 0 24 2">
              <line stroke="#565e74" strokeDasharray="3,2" strokeWidth="2" x1="0" x2="24" y1="1" y2="1" />
            </svg>
            <span className="font-caption-ui text-caption-ui text-on-surface-variant">Async Event</span>
          </div>
        </div>

        {/* Latency Propagation Callout */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-error-container text-on-error-container font-mono-badge text-mono-badge font-semibold">
          <span className="material-symbols-outlined text-[13px] text-error">warning</span>
          <span>CASCADE IMPACT: +{topology?.cascadeLatencyAddedMs ?? 806}ms propagated upstream</span>
        </div>
      </div>

      {/* Primary Split Workspace: Interactive Flow Canvas + Active Inspector */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-md items-start">
        {/* Topology Canvas (8 cols on xl, 9 on 2xl) */}
        <div className="xl:col-span-8 2xl:col-span-9 bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-space-md shadow-sm relative overflow-hidden flex flex-col min-h-[700px]">
          {/* Root Cause Warning Floating Pill (derived from live topology/correlation data) */}
          {(() => {
            const rootNodes = (topology?.nodes || []).filter((n) => n.isRootCause);
            if (rootNodes.length === 0) return null;
            return (
              <div className="absolute top-space-md right-space-md z-20 flex items-center gap-2 bg-error text-on-error px-3 py-1.5 rounded-lg shadow-md">
                <span className="material-symbols-outlined text-[16px]">priority_high</span>
                <span className="font-caption-ui text-caption-ui font-semibold uppercase tracking-wider">
                  Probable Root Cause: {rootNodes.map((n) => n.name).join(', ')}
                </span>
              </div>
            );
          })()}

          {/* Interactive React Flow Canvas */}
          <div className="w-full h-[620px] rounded-lg bg-surface border border-outline-variant/20 overflow-hidden relative">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodeClick={handleNodeClick}
              fitView
              attributionPosition="bottom-left"
              minZoom={0.5}
              maxZoom={1.5}
            >
              <Background color="#c7c4d8" gap={16} size={1} />
              <Controls position="top-left" showInteractive={false} />
              <MiniMap
                position="bottom-left"
                nodeStrokeColor="#3525cd"
                nodeColor="#dce9ff"
                style={{
                  height: 100,
                  width: 140,
                  backgroundColor: '#ffffff',
                  border: '1px solid #c7c4d8',
                  borderRadius: '8px',
                }}
              />
            </ReactFlow>
          </div>

          {/* Canvas Footer Status Bar */}
          <div className="mt-3 pt-space-xs flex items-center justify-between text-mono-caption font-mono-caption text-secondary border-t border-outline-variant/20">
            <div className="flex items-center gap-space-sm">
              <span>
                Clusters: <strong className="text-on-surface">{topology?.clustersCount ?? 3}</strong>
              </span>
              <span>•</span>
              <span>
                Edges: <strong className="text-on-surface">{topology?.activeEdgesCount ?? 7} active</strong>
              </span>
              <span>•</span>
              <span>
                Propagation Depth:{' '}
                <strong className="text-error font-semibold">
                  {topology?.propagationDepthHops ?? 3} Hops
                </strong>
              </span>
            </div>
            <div className="flex items-center gap-1 text-primary">
              <span className="material-symbols-outlined text-[14px]">auto_awesome</span>
              <span className="font-caption-ui text-caption-ui">Topology synchronized via OpenTelemetry 1.28</span>
            </div>
          </div>
        </div>

        {/* Active Inspector Panel (4 cols on xl, 3 on 2xl) */}
        <div className="xl:col-span-4 2xl:col-span-3 flex flex-col gap-space-md">
          {selectedNode ? (
            <div className="bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-space-md shadow-sm flex flex-col">
              {/* Header */}
              <div className="flex items-start justify-between mb-space-sm pb-space-sm bg-surface-container-low rounded-lg p-space-sm border border-outline-variant/20">
                <div className="flex flex-col truncate mr-2">
                  <span className="font-mono-caption text-mono-caption text-secondary uppercase tracking-wider font-semibold">
                    Active Inspector
                  </span>
                  <h2 className="font-title-md text-title-md text-on-surface font-bold leading-tight mt-0.5 truncate">
                    {selectedNode.name}
                  </h2>
                  <span className="font-mono-caption text-mono-caption text-outline truncate">
                    Cluster: {selectedNode.cluster || 'primary-az1'}
                  </span>
                </div>
                <span
                  className={`font-mono-badge text-mono-badge px-2 py-0.5 rounded-full font-bold uppercase shrink-0 ${
                    selectedNode.status === 'unhealthy'
                      ? 'bg-error text-on-error'
                      : selectedNode.status === 'degraded'
                      ? 'bg-secondary text-on-secondary'
                      : 'bg-secondary-container text-on-secondary-fixed'
                  }`}
                >
                  {selectedNode.status}
                </span>
              </div>

              {/* Vital Telemetry Metrics Grid */}
              <div className="grid grid-cols-2 gap-space-xs mb-space-md">
                <div className="bg-surface-container-low p-space-sm rounded-lg border border-outline-variant/20">
                  <span className="font-caption-ui text-caption-ui text-secondary block">Connection Pool</span>
                  <span
                    className={`font-mono-metric-lg text-mono-metric-lg font-semibold ${
                      selectedNode.poolSaturationPercent && selectedNode.poolSaturationPercent > 80
                        ? 'text-error'
                        : 'text-on-surface'
                    }`}
                  >
                    {selectedNode.poolSaturationPercent ?? 24}%
                  </span>
                  <span className="font-mono-caption text-mono-caption text-outline block mt-0.5">
                    {selectedNode.poolSaturationPercent && selectedNode.poolSaturationPercent > 80
                      ? '980 / 1000 Used'
                      : 'Nominal Pool Range'}
                  </span>
                </div>

                <div className="bg-surface-container-low p-space-sm rounded-lg border border-outline-variant/20">
                  <span className="font-caption-ui text-caption-ui text-secondary block">Avg Latency</span>
                  <span
                    className={`font-mono-metric-lg text-mono-metric-lg font-semibold ${
                      selectedNode.latencyMs > 1000
                        ? 'text-error'
                        : selectedNode.latencyMs > 200
                        ? 'text-tertiary'
                        : 'text-on-surface'
                    }`}
                  >
                    {selectedNode.latencyMs}ms
                  </span>
                  <span className="font-mono-caption text-mono-caption text-secondary block mt-0.5">
                    Throughput: {selectedNode.throughputStr}
                  </span>
                </div>

                <div className="bg-surface-container-low p-space-sm rounded-lg border border-outline-variant/20">
                  <span className="font-caption-ui text-caption-ui text-secondary block">Error Rate</span>
                  <span
                    className={`font-mono-metric-lg text-mono-metric-lg font-semibold ${
                      selectedNode.errorRatePercent > 5
                        ? 'text-error'
                        : selectedNode.errorRatePercent > 1
                        ? 'text-tertiary'
                        : 'text-primary'
                    }`}
                  >
                    {selectedNode.errorRatePercent.toFixed(2)}%
                  </span>
                  <span className="font-mono-caption text-mono-caption text-outline block mt-0.5">
                    {selectedNode.errorRatePercent > 1.0 ? 'PoolTimeoutEx' : 'Nominal 2xx'}
                  </span>
                </div>

                <div className="bg-surface-container-low p-space-sm rounded-lg border border-outline-variant/20">
                  <span className="font-caption-ui text-caption-ui text-secondary block">CPU Saturation</span>
                  <span className="font-mono-metric-lg text-mono-metric-lg text-on-surface font-semibold">
                    {selectedNode.cpuSaturationPercent ?? 45}%
                  </span>
                  <span className="font-mono-caption text-mono-caption text-outline block mt-0.5">
                    8 vCPUs (db.r6g.2xl)
                  </span>
                </div>
              </div>

              {/* Upstream Callers Traffic Split */}
              {selectedNode.upstreamCallers && selectedNode.upstreamCallers.length > 0 && (
                <div className="mb-space-md">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-caption-ui text-caption-ui text-secondary font-semibold uppercase tracking-wider">
                      Upstream Ingress Callers
                    </span>
                    <span className="font-mono-caption text-mono-caption text-outline">
                      {selectedNode.upstreamCallers.reduce((acc, c) => acc + c.rps, 0).toLocaleString()} rps total
                    </span>
                  </div>

                  <div className="flex flex-col gap-2">
                    {selectedNode.upstreamCallers.map((caller) => (
                      <div
                        key={caller.name}
                        className="bg-surface-container-low p-2 rounded-lg border border-outline-variant/20"
                      >
                        <div className="flex items-center justify-between font-caption-ui text-caption-ui mb-1">
                          <span className="font-semibold text-on-surface">{caller.name}</span>
                          <span className="font-mono-body text-mono-body font-semibold text-on-surface-variant">
                            {caller.sharePercent}% ({caller.rps.toLocaleString()} rps)
                          </span>
                        </div>
                        <div className="w-full bg-surface-container-high h-1.5 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              selectedNode.status === 'unhealthy'
                                ? 'bg-error'
                                : selectedNode.status === 'degraded'
                                ? 'bg-secondary'
                                : 'bg-primary'
                            }`}
                            style={{ width: `${caller.sharePercent}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* AI Copilot Recommendation */}
              {selectedNode.aiRecommendation && (
                <div className="bg-primary-fixed/20 border border-primary/20 rounded-xl p-space-sm mb-space-md">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-1.5 text-primary">
                      <span className="material-symbols-outlined text-[16px]">auto_awesome</span>
                      <span className="font-caption-ui text-caption-ui font-bold uppercase tracking-wider">
                        AI Copilot Recommendation
                      </span>
                    </div>
                    <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant font-medium">
                      Simulated Demo
                    </span>
                  </div>
                  <p className="font-body-default text-body-default text-on-surface leading-snug">
                    {selectedNode.aiRecommendation.summary}
                  </p>
                  <div className="mt-2.5 pt-2 flex items-center justify-between border-t border-primary/10">
                    <button
                      className="text-primary hover:text-on-primary-fixed-variant font-caption-ui text-caption-ui font-semibold flex items-center gap-1 cursor-pointer"
                      type="button"
                      onClick={() =>
                        alert(
                          `Simulated Dry-Run: ${selectedNode.aiRecommendation?.actionLabel}\nNo actual infrastructure changes were executed.`
                        )
                      }
                    >
                      <span className="material-symbols-outlined text-[14px]">terminal</span>
                      <span>{selectedNode.aiRecommendation.actionLabel}</span>
                    </button>
                    <span className="font-mono-caption text-mono-caption text-outline">
                      Confidence: {selectedNode.aiRecommendation.confidencePercent}%
                    </span>
                  </div>
                </div>
              )}

              {/* Quick Operational Actions */}
              <div className="flex flex-col gap-space-xs pt-space-xs border-t border-outline-variant/20">
                <Button
                  variant="surface"
                  icon="insights"
                  onClick={() => navigate(`/traces?service=${encodeURIComponent(selectedNode.id)}`)}
                >
                  Inspect Service Traces
                </Button>
                <Button
                  variant="surface"
                  icon="article"
                  onClick={() => navigate(`/logs?service=${encodeURIComponent(selectedNode.id)}`)}
                >
                  Inspect Service Logs
                </Button>
                <Button
                  variant="primary"
                  icon="auto_awesome"
                  onClick={() => navigate('/ai-investigations')}
                >
                  Open Multi-Signal RCA
                </Button>
                <Button
                  variant="secondary"
                  icon="crisis_alert"
                  onClick={() => navigate('/incidents')}
                >
                  Open Incidents War Room
                </Button>
              </div>
            </div>
          ) : (
            <div className="bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-space-lg text-center text-secondary">
              Select a node in the graph to inspect its telemetry and cascade metrics.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
