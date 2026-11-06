/**
 * Types representing deterministic cross-service anomaly correlation and probable root-cause ranking.
 */

export interface RankingDimensionScore {
  score: number;
  weight: number;
  weighted_score: number;
  reason: string;
}

export interface RootCauseRankingBreakdown {
  temporal_precedence: RankingDimensionScore;
  topological_position: RankingDimensionScore;
  blast_radius: RankingDimensionScore;
  severity_magnitude: RankingDimensionScore;
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

