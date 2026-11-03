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
  confidenceWeight: number; // percentage e.g. 99
}

export interface Hypothesis {
  rank: number;
  title: string;
  candidateName: string;
  probabilityScore: number; // percentage e.g. 94
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
  id: string; // e.g. "INV-2024-8492"
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
}

