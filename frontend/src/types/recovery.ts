/**
 * Types representing Phase 5: Telemetry-Based Recovery Verification.
 */

export type RecoveryOutcome =
  | 'RECOVERED'
  | 'NOT_RECOVERED'
  | 'PARTIALLY_RECOVERED'
  | 'INCONCLUSIVE';

export type VerificationStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED';

export type CheckStatus =
  | 'PASSED'
  | 'FAILED'
  | 'INCONCLUSIVE'
  | 'SKIPPED';

export interface TelemetryCheckResult {
  check_name: string;
  status: CheckStatus;
  metric_name?: string | null;
  observed_value?: number | null;
  baseline_expected?: string | number | null;
  details: string;
}

export interface RecoveryVerificationRequest {
  verification_window_seconds?: number;
  min_sample_count?: number;
}

export interface RecoveryVerificationResponse {
  id: string;
  incident_id: string;
  remediation_id: string;
  project_id: string;
  execution_attempt_id?: string | null;
  target_service: string;
  status: VerificationStatus;
  recovery_outcome?: RecoveryOutcome | null;
  verification_window_start?: string | null;
  verification_window_end?: string | null;
  sample_count: number;
  checks_summary: TelemetryCheckResult[];
  evidence_snapshot: Record<string, any>;
  explanation?: string | null;
  error_message?: string | null;
  verified_by?: string | null;
  suggested_incident_status?: string | null;
  created_at: string;
  updated_at: string;
}
