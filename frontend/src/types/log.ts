export type LogSeverity = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface ApplicationLogItem {
  id: string;
  project_id: string;
  service_id: string;
  service_slug: string | null;
  service_name: string | null;
  timestamp: string;
  level: LogSeverity | string;
  message: string;
  request_id: string | null;
  trace_id: string | null;
  span_id: string | null;
  attributes_json: Record<string, unknown>;
  exception_type: string | null;
  exception_message: string | null;
}

export interface PaginatedLogsResponse {
  items: ApplicationLogItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

