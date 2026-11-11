import { HealthStatus } from './common';

export type ServiceTier = 0 | 1 | 2;

export interface ServiceItem {
  id: string;
  name: string;
  identifier: string;
  tier: ServiceTier;
  ownerTeam: string;
  environment: string;
  status: HealthStatus;
  requestRateRps: number;
  errorRatePercent: number;
  p95LatencyMs: number;
  lastSeen: string;
  lastDeployment?: string;
  availabilityPercent?: number;
  cpuSaturationPercent?: number;
  memoryUsagePercent?: number;
  sparkline?: number[];
  dependenciesCount?: number;
  upstreamDependencies?: string[];
  downstreamDependencies?: string[];
  description?: string;
}

export interface ServicesOverviewStats {
  totalServices: number;
  healthyCount: number;
  degradedCount: number;
  unhealthyCount: number;
  ingestionBandwidth: string;
  logPayloadDaily: string;
  sampleIngestionRatePerSec?: number | null;
  totalMetricSamples?: number;
  totalLogs?: number;
  totalSpans?: number;
  applicationRequestRateRps?: number | null;
  totalRequests?: number;
  requestRateStatus?: 'available' | 'no_traffic' | 'insufficient_data';
}

