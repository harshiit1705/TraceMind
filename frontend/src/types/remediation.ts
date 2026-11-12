/**
 * Types representing Phase 4: Human-Approved Remediation Workflow.
 */

export type RemediationStatus =
  | 'PROPOSED'
  | 'APPROVED'
  | 'REJECTED'
  | 'EXECUTING'
  | 'EXECUTED'
  | 'FAILED'
  | 'CANCELLED';

export type RemediationExecutionMode = 'REAL' | 'SIMULATED';

export type AllowlistedAction =
  | 'RESET_SERVICE_FAULTS'
  | 'RESTART_SERVICE'
  | 'SCALE_REPLICAS'
  | 'ROLLBACK_DEPLOYMENT'
  | 'FLUSH_CONNECTION_POOL'
  | 'DRAIN_TRAFFIC';

export interface RemediationDetail {
  id: string;
  investigation_id?: string | null;
  finding_id?: string | null;
  title: string;
  action_type?: string | null;
  target_service: string;
  description: string;
  action_name: AllowlistedAction | string;
  action_parameters?: Record<string, any>;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  status: RemediationStatus;
  preconditions: string[];
  rollback_procedure?: string | null;
  expected_result?: string | null;
  verification_steps: string[];
  requires_human_approval: boolean;
  approved_by?: string | null;
  approved_at?: string | null;
  approval_notes?: string | null;
  rejected_by?: string | null;
  rejected_at?: string | null;
  rejection_reason?: string | null;
  executed_by?: string | null;
  executed_at?: string | null;
  execution_mode?: RemediationExecutionMode | null;
  execution_idempotency_key?: string | null;
  execution_result_json?: Record<string, any> | null;
  execution_error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  is_demo?: boolean;
}

export interface RemediationApproveRequest {
  approver_name: string;
  approval_notes?: string | null;
}

export interface RemediationRejectRequest {
  rejector_name: string;
  rejection_reason: string;
}

export interface RemediationExecuteRequest {
  executor_name: string;
  idempotency_key?: string | null;
}

export interface RemediationCancelRequest {
  cancelled_by: string;
  cancellation_reason?: string | null;
}

export interface RemediationProposeRequest {
  title: string;
  description: string;
  target_service: string;
  action_name: AllowlistedAction;
  action_parameters?: Record<string, any>;
  risk_level?: 'LOW' | 'MEDIUM' | 'HIGH';
  preconditions?: string[];
  rollback_procedure?: string;
  expected_result?: string;
  verification_steps?: string[];
  proposer_name?: string;
}

