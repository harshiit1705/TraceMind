import React, { memo } from 'react';
import { Handle, Position, NodeProps, Node } from '@xyflow/react';
import { TopologyNodeData } from '../../types';

export type ServiceNodeType = Node<TopologyNodeData, 'serviceNode'>;

export const ServiceNode: React.FC<NodeProps<ServiceNodeType>> = memo(({ data, selected }) => {
  const node = data;

  const isUnhealthy = node.status === 'unhealthy';
  const isDegraded = node.status === 'degraded';
  const isRootCause = node.isRootCause;

  return (
    <div
      className={`relative w-56 rounded-xl p-space-sm shadow-md transition-all cursor-pointer ${
        selected
          ? 'ring-2 ring-primary ring-offset-2 scale-105'
          : ''
      } ${
        isUnhealthy
          ? 'bg-error-container text-on-error-container border-2 border-error/50'
          : isDegraded
          ? 'bg-surface-container border border-secondary/40 text-on-surface'
          : 'bg-surface-container-low border border-outline-variant/30 text-on-surface hover:bg-surface-container'
      }`}
    >
      {/* React Flow Handles for Directed Connections */}
      <Handle
        type="target"
        position={Position.Left}
        className="w-2.5 h-2.5 !bg-primary border-2 border-surface-container-lowest"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="w-2.5 h-2.5 !bg-primary border-2 border-surface-container-lowest"
      />

      {/* Floating Status / Root Cause Pill */}
      {isRootCause && (
        <div className="absolute -top-3 right-2 font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-error text-on-error font-bold uppercase tracking-wider shadow-sm animate-pulse">
          ROOT FAULT
        </div>
      )}
      {!isRootCause && isDegraded && (
        <div className="absolute -top-2.5 right-2 font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-secondary text-on-secondary font-semibold uppercase">
          Degraded
        </div>
      )}

      {/* Node Header */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 truncate">
          {isUnhealthy ? (
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-error opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-error" />
            </span>
          ) : isDegraded ? (
            <span className="w-2 h-2 rounded-full bg-secondary shrink-0" />
          ) : (
            <span className="w-2 h-2 rounded-full bg-tertiary shrink-0" />
          )}
          <span className="font-title-md text-title-md font-semibold truncate">
            {node.name}
          </span>
        </div>
        <span className="font-mono-badge text-mono-badge px-1 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-medium shrink-0 ml-1">
          {node.role.split(' ')[0]}
        </span>
      </div>

      {/* Metrics Card Inside Node */}
      <div className="bg-surface-container-lowest text-on-surface rounded-lg p-2 shadow-xs">
        <div className="grid grid-cols-2 gap-1 font-mono-body text-mono-body">
          <div>
            <span className="block font-caption-ui text-caption-ui text-outline uppercase text-[10px]">
              {node.identifier.startsWith('db:') ? 'Avg Lat' : 'Latency'}
            </span>
            <span
              className={`font-medium ${
                isUnhealthy || node.latencyMs > 1000
                  ? 'text-error font-bold'
                  : isDegraded
                  ? 'text-secondary font-semibold'
                  : 'text-on-surface'
              }`}
            >
              {node.latencyMs}ms
            </span>
          </div>

          <div>
            <span className="block font-caption-ui text-caption-ui text-outline uppercase text-[10px]">
              Error Rate
            </span>
            <span
              className={`font-medium ${
                isUnhealthy || node.errorRatePercent > 5
                  ? 'text-error font-bold'
                  : isDegraded
                  ? 'text-error font-medium'
                  : 'text-tertiary'
              }`}
            >
              {node.errorRatePercent.toFixed(2)}%
            </span>
          </div>
        </div>

        {/* Pool Saturation Progress Bar (for Database) */}
        {node.poolSaturationPercent && node.poolSaturationPercent > 50 && (
          <div className="mt-1.5 pt-1.5 border-t border-outline-variant/20">
            <div className="flex justify-between items-center text-mono-caption font-mono-caption text-[10px] mb-0.5">
              <span className="text-error font-bold">Pool: {node.poolSaturationPercent}%</span>
              <span className="text-outline">{node.throughputStr}</span>
            </div>
            <div className="w-full bg-surface-container-high h-1.5 rounded-full overflow-hidden">
              <div
                className="bg-error h-full rounded-full transition-all"
                style={{ width: `${node.poolSaturationPercent}%` }}
              />
            </div>
          </div>
        )}

        {/* Throughput tag for non-pool nodes */}
        {(!node.poolSaturationPercent || node.poolSaturationPercent <= 50) && (
          <div className="mt-1.5 pt-1 border-t border-outline-variant/15 flex items-center justify-between text-mono-caption font-mono-caption text-[10px] text-outline">
            <span>Throughput</span>
            <span className="text-on-surface font-medium">{node.throughputStr}</span>
          </div>
        )}
      </div>
    </div>
  );
});

ServiceNode.displayName = 'ServiceNode';
