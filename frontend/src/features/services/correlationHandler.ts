import type { ServiceItem } from '../../types';
import type { apiClient } from '../../services/apiClient';

export interface IncidentCorrelationParams {
  selectedService: ServiceItem | null;
  services: ServiceItem[];
  api: typeof apiClient;
  navigate: (path: string) => void;
  setIsCorrelating: (loading: boolean) => void;
  setFeedback: (feedback: { type: 'success' | 'warning' | 'error'; message: string } | null) => void;
}

export async function executeIncidentCorrelation({
  selectedService,
  services,
  api,
  navigate,
  setIsCorrelating,
  setFeedback,
}: IncidentCorrelationParams): Promise<boolean> {
  setIsCorrelating(true);
  setFeedback(null);

  try {
    // 1. Resolve project ID dynamically:
    // First priority: selectedService.projectId or selectedService.project_id
    let targetProjectId = selectedService?.projectId || selectedService?.project_id;

    // Second priority: from any loaded service
    if (!targetProjectId) {
      const withProj = services.find((s) => s.projectId || s.project_id);
      targetProjectId = withProj?.projectId || withProj?.project_id;
    }

    // Third priority: fetch active project list
    if (!targetProjectId) {
      const projRes = await api.getProjects();
      const projs = projRes.data || [];
      const preferred = projs.find(
        (p) => p.slug === 'core-ecommerce' || p.name.toLowerCase().includes('core e-commerce')
      );
      targetProjectId = preferred ? preferred.id : projs[0]?.id;
    }

    if (!targetProjectId) {
      throw new Error('No active project could be determined for anomaly correlation.');
    }

    // 2. Call correlation API with exact contract
    const res = await api.correlateIncidents({
      project_id: targetProjectId,
    });

    // 3. Extract actual correlation evaluation metrics
    const totalAnomalies = res.data?.total_anomalies_evaluated ?? 0;
    const groupCount = res.data?.correlation_groups_count ?? (res.data?.groups?.length ?? 0);

    if (groupCount === 0) {
      const message = totalAnomalies === 0
        ? 'No anomaly events were found in the evaluation window. No incident was created. Verify recent metric ingestion and anomaly detection before retrying.'
        : `${totalAnomalies} anomaly event(s) were evaluated, but no related group met the correlation rules. No incident was created.`;

      setFeedback({
        type: 'warning',
        message,
      });
      return false;
    }

    setFeedback({
      type: 'success',
      message: `Correlation evaluation completed: ${groupCount} group(s) identified across ${totalAnomalies} anomaly event(s).`,
    });

    // The API confirms persisted correlation groups, not necessarily newly-created incidents.
    // Refresh the incident queue only when at least one group was returned.
    navigate('/incidents');
    return true;
  } catch (err: unknown) {
    const e = err as { message?: string };
    setFeedback({
      type: 'error',
      message: e.message || 'Correlation evaluation failed. Please verify telemetry ingestion and try again.',
    });
    return false;
  } finally {
    setIsCorrelating(false);
  }
}
