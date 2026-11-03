export type DataMode = 'mock' | 'api';

export interface ApiResponse<T> {
  data: T;
  source: DataMode;
  timestamp: string;
  cached?: boolean;
}

export interface ApiError {
  message: string;
  code?: string;
  status?: number;
  details?: Record<string, unknown>;
}

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy';
export type SeverityLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

export interface MetricSummary {
  label: string;
  value: string | number;
  change?: string;
  changeType?: 'positive' | 'negative' | 'neutral';
  status?: HealthStatus;
  subtext?: string;
}

