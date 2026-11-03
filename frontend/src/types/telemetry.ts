import { HealthStatus } from './common';

export interface TelemetryTimeSeriesPoint {
  time: string;
  timestamp: number;
  throughputRps: number;
  baselineThroughputRps: number;
  errorRatePercent: number;
  p50Ms: number;
  p90Ms: number;
  p95Ms: number;
  p99Ms: number;
  isAnomaly?: boolean;
}

export interface TelemetryOverviewData {
  timeRange: '15m' | '1h' | '24h';
  points: TelemetryTimeSeriesPoint[];
  currentThroughputRps: number;
  meanThroughputRps: number;
  peakThroughputRps: number;
  currentErrorRatePercent: number;
  peakErrorRatePercent: number;
  currentP95Ms: number;
  baselineP95Ms: number;
  currentP99Ms: number;
}

export interface TopologyNodeData {
  [key: string]: unknown;
  id: string;
  name: string;
  identifier: string;
  role: string;
  tier: 0 | 1 | 2;
  status: HealthStatus;
  latencyMs: number;
  errorRatePercent: number;
  throughputStr: string;
  cluster?: string;
  poolSaturationPercent?: number;
  isRootCause?: boolean;
  isAnomalous?: boolean;
  cpuSaturationPercent?: number;
  upstreamCallers?: Array<{
    name: string;
    sharePercent: number;
    rps: number;
  }>;
  aiRecommendation?: {
    summary: string;
    actionLabel: string;
    confidencePercent: number;
  };
  downstreamImpact?: {
    revenueAtRiskPerMin: string;
    impactedActiveSessions: number;
    tierDegraded: string;
    assignedTo: string;
  };
}

export interface TopologyEdgeItem {
  id: string;
  source: string;
  target: string;
  protocol: 'HTTP/REST' | 'gRPC' | 'Async Event' | 'SQL';
  isAnomalous: boolean;
  isCriticalPath?: boolean;
  label?: string;
}

export interface ServiceTopologyData {
  nodes: TopologyNodeData[];
  edges: TopologyEdgeItem[];
  clustersCount: number;
  activeEdgesCount: number;
  propagationDepthHops: number;
  cascadeLatencyAddedMs: number;
}

