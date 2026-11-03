export interface IntegrationChannel {
  id: string;
  provider: 'Slack' | 'PagerDuty' | 'Webhook';
  name: string;
  targetService: string;
  status: 'ACTIVE' | 'PAUSED' | 'ERROR';
}

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
  avatarUrl?: string;
  initials?: string;
  twoFactorEnforced: boolean;
  lastActive: string;
}

export interface SystemSettings {
  workspaceName: string;
  tenantId: string;
  primaryRegion: string;
  retentionWindow: string;
  spikeguardEnabled: boolean;
  maxSpansPerSec: number;
  aiMode: 'Assisted' | 'Full Autonomous';
  heuristicConfidenceThreshold: number;
  piiScrubbingEnabled: boolean;
  integrations: IntegrationChannel[];
  teamMembers: TeamMember[];
}

