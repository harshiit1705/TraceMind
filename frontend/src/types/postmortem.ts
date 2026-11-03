export interface PostmortemChronologyItem {
  timeUtc: string;
  source: string;
  operationalAction: string;
  tagColor?: string;
}

export interface PostmortemActionItem {
  item: string;
  type: 'Architecture' | 'Detection' | 'Configuration';
  owner: string;
  priority: 'P0' | 'P1' | 'P2';
  targetDate: string;
  status: 'In Progress' | 'Completed' | 'Staged';
}

export interface PostmortemReport {
  id: string;
  incidentId: string;
  title: string;
  commander: string;
  scribe: string;
  incidentDate: string;
  executiveSummary: string;
  impactAnalysis: {
    businessImpact: string;
    technicalImpact: string;
    revenueAtRisk?: string;
    abandonedCarts?: string;
    p99Latency?: string;
  };
  chronology: PostmortemChronologyItem[];
  whatWentWell: string[];
  whatWentWrong: string[];
  actionItems: PostmortemActionItem[];
}

