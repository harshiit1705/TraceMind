import { SeverityLevel } from './common';

export type IncidentStatus = 'DETECTED' | 'INVESTIGATING' | 'ACKNOWLEDGED' | 'MITIGATED' | 'RESOLVED';

export interface ImpactedEntity {
  name: string;
  metricSummary: string;
  status: 'critical' | 'degraded' | 'normal';
}

export interface IncidentEvent {
  id: string;
  timestamp: string;
  relativeTime: string;
  title: string;
  source: string;
  description: string;
  type: 'anomaly' | 'alert' | 'agent' | 'human' | 'action';
  actionScript?: string;
  actionStatus?: 'pending' | 'review' | 'executed';
}

export interface IncidentItem {
  id: string; // e.g., "INC-8492"
  title: string;
  severity: SeverityLevel;
  status: IncidentStatus;
  startedAt: string;
  activeDuration: string;
  commander: {
    name: string;
    role: string;
    avatarUrl?: string;
  };
  impactedEntities: ImpactedEntity[];
  rootCauseSummary?: string;
  correlatedTracesCount?: number;
  aiRemediationAvailable?: boolean;
  affectedServices: string[];
  correlationGroupId?: string | null;
  correlation_group_id?: string | null;
  projectId?: string | null;
  project_id?: string | null;
  isDemo?: boolean;
  is_demo?: boolean;
  summary?: string;
  mitigatedAt?: string | null;
  resolvedAt?: string | null;
}

export interface IncidentsKpiStats {
  activeCount: number;
  criticalImpactCount: number;
  acknowledgedCount: number;
  resolved24hCount: number;
  mttdFormatted: string;
  mttrFormatted: string;
}

