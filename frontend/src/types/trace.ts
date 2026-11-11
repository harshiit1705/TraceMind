export type SpanStatus = 'ok' | 'error' | 'skipped';

export interface SpanItem {
  id: string;
  span_id?: string;
  parent_span_id?: string | null;
  name: string;
  service: string;
  service_slug?: string;
  operation: string;
  span_kind?: string;
  durationMs: number;
  offsetPercent: number;
  widthPercent: number;
  status: SpanStatus;
  httpStatus?: number | null;
  isBottleneck?: boolean;
  depth: number;
  hasChildren?: boolean;
  request_id?: string | null;
  attributes?: Record<string, string | number | boolean>;
  exception?: {
    type: string;
    message: string;
    stackTrace: string[];
  } | null;
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

