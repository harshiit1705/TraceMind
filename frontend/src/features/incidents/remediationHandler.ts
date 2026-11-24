import type React from 'react';
import type { apiClient } from '../../services/apiClient';
import type { RemediationDetail, RemediationProposeRequest } from '../../types';

export interface ProposeFaultResetParams {
  incident: {
    id: string;
    project_id?: string | null;
    projectId?: string | null;
  };
  api: typeof apiClient;
  remediations?: RemediationDetail[];
  setActionInProgress: (inProgress: boolean) => void;
  setRemediationError: (error: string | null) => void;
  setRemediations: React.Dispatch<React.SetStateAction<RemediationDetail[]>> | ((updater: (prev: RemediationDetail[]) => RemediationDetail[]) => void);
  loadTimeline: (id: string) => Promise<void>;
}

/**
 * Resolves the project ID from an incident object, checking snake_case and camelCase attributes.
 */
export function resolveIncidentProjectId(incident: {
  project_id?: string | null;
  projectId?: string | null;
}): string | undefined {
  return (incident.project_id || incident.projectId) ?? undefined;
}

/**
 * Checks whether an active RESET_SERVICE_FAULTS proposal already exists.
 * Active statuses are PROPOSED (awaiting approval), APPROVED (ready for execution), and EXECUTING.
 * Terminated statuses like REJECTED, CANCELLED, FAILED, and EXECUTED do not block a new proposal.
 */
export function hasActiveFaultResetRemediation(remediations: RemediationDetail[]): boolean {
  return remediations.some(
    (r) =>
      r.action_name === 'RESET_SERVICE_FAULTS' &&
      (r.status === 'PROPOSED' || r.status === 'APPROVED' || r.status === 'EXECUTING')
  );
}

/**
 * Executes proposing the fault reset remediation action for an incident.
 * Validates that project ID exists; if missing, displays a clear error and aborts submission.
 * Validates that no duplicate active RESET_SERVICE_FAULTS action exists.
 */
export async function executeProposeFaultReset({
  incident,
  api,
  remediations,
  setActionInProgress,
  setRemediationError,
  setRemediations,
  loadTimeline,
}: ProposeFaultResetParams): Promise<boolean> {
  const projId = resolveIncidentProjectId(incident);
  if (!projId) {
    setRemediationError('Cannot propose remediation: Missing project ID on incident.');
    return false;
  }

  if (remediations && hasActiveFaultResetRemediation(remediations)) {
    setRemediationError('An active fault-reset remediation is already pending approval or execution.');
    return false;
  }

  setActionInProgress(true);
  setRemediationError(null);
  try {
    const payload: RemediationProposeRequest = {
      title: 'Reset Payment Service Faults and Connection Locks',
      target_service: 'payment-service',
      description: 'Reset faults and clear deadlocks on payment-service to restore throughput.',
      action_name: 'RESET_SERVICE_FAULTS',
      risk_level: 'LOW',
      preconditions: ['Payment error rate > 5% or latency > 1000ms'],
      rollback_procedure: 'Re-route traffic or restart container if lock persists',
      expected_result: 'Payment service error rate drops to 0% and latency normalizes',
      verification_steps: ['Check GET /health on payment-service'],
      proposer_name: 'Alex Chen (Staff SRE)',
    };

    const res = await api.proposeRemediation(incident.id, payload, projId);
    setRemediations((prev) => [...prev, res.data]);
    await loadTimeline(incident.id);
    return true;
  } catch (err: unknown) {
    const e = err as { message?: string };
    setRemediationError(e.message || 'Failed to propose remediation');
    return false;
  } finally {
    setActionInProgress(false);
  }
}
