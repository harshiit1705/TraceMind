export type SpanStatus = 'ok' | 'error' | 'skipped';

export interface SpanItem {
  id: string;
  name: string;
  service: string;
  operation: string;
  durationMs: number;
  offsetPercent: number;
  widthPercent: number;
  status: SpanStatus;
  httpStatus?: number;
  isBottleneck?: boolean;
  depth: number;
  hasChildren?: boolean;
  attributes?: Record<string, string | number | boolean>;
  exception?: {
    type: string;
    message: string;
    stackTrace: string[];
  };
}

export interface TraceItem {
  id: string; // e.g. "tr-9f82d4e7a1b0c"
  rootService: string;
  rootEndpoint: string;
  durationMs: number;
  spansCount: number;
  status: '200 OK' | '504 TIMEOUT' | '500 ERROR' | '502 BAD GATEWAY';
  statusCode: number;
  timestamp: string;
  anomalous: boolean;
  client?: string;
  host?: string;
  spans?: SpanItem[];
}

