/**
 * Types representing AI incident investigations in TraceMind.
 * Supports both:
 * 1. Sprint 5.1+ evidence-grounded Gemini investigations linked to correlation groups
 * 2. Legacy Phase 2.1 simulated demo investigations
 */

// --- Sprint 5.1+ Evidence-Grounded Gemini Investigation Types ---

export type RemediationActionType = 'configuration' | 'scaling' | 'restart' | 'failover' | 'rollback';
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export interface TimelineEvidenceEvent {
  timestamp: string;
  event_id: string;
  service_id: string;
  service_name: string;
  metric_name: string;
  observation: string;
  severity: string;
}

export interface RootCauseEvidenceExplanation {
  candidate_id: string;
  service_id: string;
  service_name: string;
  explanation: string;
  contributing_factors: string[];
}

export interface EvidenceReference {
  source_record_type: string; // 'anomaly_event' | 'service_dependency' | 'baseline'
  source_id: string;
  supported_field: string;
  summary_citation: string;
}

export interface UncertaintyGap {
  category: string;
  description: string;
  impact_on_confidence: string;
}

export interface InvestigationStep {
  step_number: number;
  target_service: string;
  action: string;
  purpose: string;
}

export interface RemediationRecommendation {
  title: string;
  action_type: RemediationActionType;
  target_service: string;
  description: string;
  risk_level: RiskLevel;
  preconditions: string[];
  rollback_procedure: string;
  requires_human_approval: boolean;
  command_snippet?: string | null;
  expected_result?: string | null;
  verification_steps?: string[];
}

export interface InvestigationResult {
  incident_summary: string;
  conclusion_status?: 'CONCLUSIVE' | 'CORRELATION_ONLY' | 'INCONCLUSIVE' | string;
  confidence_level?: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  confidence_explanation?: string | null;
  suspected_operation?: string | null;
  timeline: TimelineEvidenceEvent[];
  root_cause_analysis: RootCauseEvidenceExplanation;
  alternative_explanations?: string[];
  evidence_references: EvidenceReference[];
  contradictory_evidence?: string[];
  neutral_evidence?: string[];
  uncertainties_and_gaps: UncertaintyGap[];
  prioritized_investigation_steps: InvestigationStep[];
  remediation_recommendations: RemediationRecommendation[];
}

export interface GroundedInvestigationResponse {
  id: string;
  correlation_group_id?: string | null;
  incident_id?: string | null;
  provider: string;
  model_name: string;
  prompt_version: string;
  schema_version: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  evidence_hash?: string | null;
  evidence_stale?: boolean;
  latest_evidence_hash?: string | null;
  result?: InvestigationResult | null;
  investigation_json?: InvestigationResult | null;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  latency_ms?: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
  is_demo?: boolean;
}

export interface InvestigationGenerateRequest {
  correlation_group_id: string;
  force_regenerate?: boolean;
}

// --- Legacy Phase 2.1 Demo Investigation Types ---

export interface PropagationStep {
  step: number;
  layer: 'Origin Node' | 'Infra Layer' | 'Microservices' | 'Edge Ingress';
  timestamp: string;
  title: string;
  description: string;
  impactTag: string;
  isRootCause: boolean;
  severity: 'critical' | 'warning' | 'normal';
}

export interface CorrelatedEvidence {
  id: string;
  type: 'Metric' | 'Trace' | 'Log';
  targetService: string;
  observation: string;
  timestamp: string;
  confidenceWeight: number;
}

export interface Hypothesis {
  rank: number;
  title: string;
  candidateName: string;
  probabilityScore: number;
  status: 'Confirmed' | 'Disproven' | 'Evaluating';
  description: string;
  evidenceItems: string[];
}

export interface RemediationActionItem {
  id: string;
  type: 'Immediate' | 'Short-Term' | 'Architectural';
  title: string;
  description: string;
  commandSnippet?: string;
  risk: 'Low' | 'Medium' | 'High';
  isDryRunSafe: boolean;
}

export interface AiInvestigationSummary {
  id: string;
  incidentId: string;
  agentName: string;
  status: 'Analysis Complete' | 'Analyzing' | 'Pending Remediation';
  elapsedTime: string;
  correlationScope: number;
  spansAnalyzed: number;
  confidenceScore: number;
  rootCauseTitle: string;
  rootCauseDescription: string;
  propagationGraph: PropagationStep[];
  evidence: CorrelatedEvidence[];
  hypotheses: Hypothesis[];
  remediations: RemediationActionItem[];
  is_demo?: boolean;
}
