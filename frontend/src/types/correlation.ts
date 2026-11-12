/**
 * Types representing deterministic cross-service anomaly correlation and probable root-cause ranking.
 */

export interface RankingDimensionScore {
  score: number;
  weight: number;
  weighted_score: number;
  reason: string;
  available?: boolean;
}

export interface RootCauseRankingBreakdown {
  temporal_precedence: RankingDimensionScore;
  topological_position: RankingDimensionScore;
  blast_radius: RankingDimensionScore;
  severity_magnitude: RankingDimensionScore;
  metric_deviation?: RankingDimensionScore | null;
  log_evidence?: RankingDimensionScore | null;
  trace_bottleneck?: RankingDimensionScore | null;
}

export interface SignalCoverageSummary {
  metrics_available: boolean;
  logs_available: boolean;
  traces_available: boolean;
  topology_available: boolean;
  anomalies_count: number;
  metric_samples_count: number;
  log_entries_count: number;
  error_logs_count: number;
  trace_spans_count: number;
  traces_count: number;
  incomplete_traces_count: number;
  observed_signals: string[];
  missing_signals: string[];
}

export interface ServiceMetricEvidence {
  service_id: string;
  service_slug: string;
  service_name: string;
  metric_name: string;
  metric_unit: string;
  sample_count: number;
  baseline_sample_count: number;
  min_value: number;
  max_value: number;
  mean_value: number;
  p95_value?: number | null;
  baseline_mean?: number | null;
  deviation_pct?: number | null;
  is_anomalous: boolean;
  status: string;
  first_breach_at?: string | null;
}

export interface CorrelatedLogHighlight {
  log_id: string;
  service_id: string;
  service_slug: string;
  service_name: string;
  timestamp: string;
  level: string;
  message: string;
  trace_id?: string | null;
  request_id?: string | null;
  exception_type?: string | null;
  pattern_category?: string | null;
}

export interface BottleneckSpanEvidence {
  trace_id: string;
  span_id: string;
  parent_span_id?: string | null;
  service_id: string;
  service_slug: string;
  service_name: string;
  operation_name: string;
  span_kind: string;
  duration_ms: number;
  self_time_ms: number;
  self_time_share: number;
  status: string;
  http_status_code?: number | null;
  error_message?: string | null;
  start_time: string;
  is_origin_error: boolean;
  is_bottleneck: boolean;
  has_missing_parent: boolean;
}

export interface MultiSignalTimelineEntry {
  timestamp: string;
  signal_type: string;
  service_id: string;
  service_slug: string;
  service_name: string;
  severity: string;
  title: string;
  detail: string;
  reference_id?: string | null;
}

export interface MultiSignalEvidenceSummary {
  correlation_group_id?: string | null;
  project_id: string;
  time_window_start: string;
  time_window_end: string;
  evidence_version: string;
  evidence_hash?: string | null;
  computed_at: string;
  coverage: SignalCoverageSummary;
  metric_summaries: ServiceMetricEvidence[];
  log_highlights: CorrelatedLogHighlight[];
  trace_bottlenecks: BottleneckSpanEvidence[];
  timeline: MultiSignalTimelineEntry[];
  primary_suspected_operation?: string | null;
  affected_downstream_services: string[];
  contradictory_signals: string[];
  neutral_signals: string[];
  missing_signals: string[];
  uncertainty_notes: string[];
}

export interface RootCauseCandidate {
  rank: number;
  service_id: string;
  service_slug: string;
  service_name: string;
  service_identifier: string;
  score: number;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  is_probable_root_cause: boolean;
  breakdown: RootCauseRankingBreakdown;
  supporting_evidence: string[];
  limitations: string[];
  contradictory_evidence?: string[];
  neutral_signals?: string[];
  missing_signals?: string[];
  primary_suspected_operation?: string | null;
  affected_downstream_services?: string[];
  evidence_references?: Record<string, unknown>;
  scoring_mode?: string;
}

export interface CorrelatedEventSummary {
  event_id: string;
  service_id: string;
  service_name: string;
  service_identifier: string;
  metric_name: string;
  observed_value: number;
  expected_baseline?: number | null;
  deviation_pct?: number | null;
  severity: string;
  occurred_at: string;
  relevance_score: number;
  correlation_reason: string;
}

export interface CorrelationGroup {
  id: string;
  project_id: string;
  correlation_key: string;
  time_window_start: string;
  time_window_end: string;
  status: string;
  summary?: string | null;
  confidence_score: number;
  topology_complete: boolean;
  events_count: number;
  participating_events: CorrelatedEventSummary[];
  ranked_candidates: RootCauseCandidate[];
  evidence_summary?: MultiSignalEvidenceSummary | null;
  primary_suspected_operation?: string | null;
  uncertainty_summary?: string | null;
  created_at: string;
}

export interface CorrelationEvaluationResponse {
  project_id: string;
  evaluated_at: string;
  time_window_start: string;
  time_window_end: string;
  total_anomalies_evaluated: number;
  correlation_groups_count: number;
  groups: CorrelationGroup[];
}

