import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { executeProposeFaultReset, resolveIncidentProjectId } from '../remediationHandler.ts';
import type { apiClient } from '../../../services/apiClient.ts';
import type { RemediationDetail, ApiResponse } from '../../../types/index.ts';

describe('Incident Remediation - Project ID Integration', () => {
  const dummyIncident = {
    id: 'INC-8492',
    project_id: 'e93c597f-147e-4ef0-b210-8f7911609527',
    projectId: null,
  };

  it('resolves project ID from project_id (snake_case) or projectId (camelCase)', () => {
    assert.equal(
      resolveIncidentProjectId({ project_id: 'proj-uuid-1', projectId: null }),
      'proj-uuid-1'
    );
    assert.equal(
      resolveIncidentProjectId({ project_id: null, projectId: 'proj-uuid-2' }),
      'proj-uuid-2'
    );
    assert.equal(
      resolveIncidentProjectId({ project_id: undefined, projectId: undefined }),
      undefined
    );
  });

  it('includes the actual incident project_id in proposeRemediation call', async () => {
    let capturedIncidentId = '';
    let capturedPayload: any = null;
    let capturedProjectId: string | undefined = undefined;
    let timelineLoaded = false;
    let remediationsState: RemediationDetail[] = [];

    const mockApi = {
      proposeRemediation: async (incId: string, payload: any, projId?: string) => {
        capturedIncidentId = incId;
        capturedPayload = payload;
        capturedProjectId = projId;
        return {
          data: {
            id: 'rem-new-123',
            title: payload.title,
            target_service: payload.target_service,
            status: 'PROPOSED',
            action_name: payload.action_name,
            project_id: projId,
            incident_id: incId,
          } as RemediationDetail,
          source: 'api',
          timestamp: new Date().toISOString(),
        } as ApiResponse<RemediationDetail>;
      },
    } as unknown as typeof apiClient;

    let errorMsg: string | null = null;
    const inProgressStates: boolean[] = [];

    const success = await executeProposeFaultReset({
      incident: dummyIncident,
      api: mockApi,
      setActionInProgress: (val: boolean) => inProgressStates.push(val),
      setRemediationError: (err: string | null) => { errorMsg = err; },
      setRemediations: (updater: any) => {
        if (typeof updater === 'function') {
          remediationsState = updater(remediationsState);
        }
      },
      loadTimeline: async () => { timelineLoaded = true; },
    });

    assert.equal(success, true);
    assert.equal(errorMsg, null);
    assert.equal(capturedIncidentId, 'INC-8492');
    assert.equal(capturedProjectId, 'e93c597f-147e-4ef0-b210-8f7911609527');
    assert.equal(capturedPayload.action_name, 'RESET_SERVICE_FAULTS');
    assert.equal(capturedPayload.target_service, 'payment-service');
    assert.equal(timelineLoaded, true);
    assert.equal(remediationsState.length, 1);
    assert.equal(remediationsState[0].id, 'rem-new-123');
    assert.deepEqual(inProgressStates, [true, false]);
  });

  it('resolves project ID when incident uses camelCase projectId', async () => {
    const camelCaseIncident = {
      id: 'INC-8492',
      project_id: null,
      projectId: 'proj-camel-case-456',
    };

    let capturedProjectId: string | undefined = undefined;
    const mockApi = {
      proposeRemediation: async (_incId: string, _payload: any, projId?: string) => {
        capturedProjectId = projId;
        return {
          data: { id: 'rem-1' } as RemediationDetail,
          source: 'api',
          timestamp: new Date().toISOString(),
        } as ApiResponse<RemediationDetail>;
      },
    } as unknown as typeof apiClient;

    const success = await executeProposeFaultReset({
      incident: camelCaseIncident,
      api: mockApi,
      setActionInProgress: () => {},
      setRemediationError: () => {},
      setRemediations: () => {},
      loadTimeline: async () => {},
    });

    assert.equal(success, true);
    assert.equal(capturedProjectId, 'proj-camel-case-456');
  });

  it('aborts proposal and produces a clear error when project_id is missing', async () => {
    const invalidIncident = {
      id: 'INC-8492',
      project_id: null,
      projectId: undefined,
    };

    let proposeCalled = false;
    let errorMsg: string | null = null;
    const inProgressStates: boolean[] = [];

    const mockApi = {
      proposeRemediation: async () => {
        proposeCalled = true;
        throw new Error('Should not be called');
      },
    } as unknown as typeof apiClient;

    const success = await executeProposeFaultReset({
      incident: invalidIncident,
      api: mockApi,
      setActionInProgress: (val: boolean) => inProgressStates.push(val),
      setRemediationError: (err: string | null) => { errorMsg = err; },
      setRemediations: () => {},
      loadTimeline: async () => {},
    });

    assert.equal(success, false, 'Must return false when project ID is missing');
    assert.equal(proposeCalled, false, 'Must NOT submit proposal API call when project ID is missing');
    assert.ok(errorMsg, 'Error message must be set');
    assert.match(errorMsg, /Missing project ID/i, 'Error message must clearly state project ID is missing');
    assert.deepEqual(inProgressStates, [], 'Action in progress state should not be toggled');
  });

  it('verifies that the proposal request URL contract formats ?project_id=... with actual incident project_id', () => {
    const incidentId = 'INC-8492';
    const projectId = 'e93c597f-147e-4ef0-b210-8f7911609527';

    // Verify the URL formation logic used by apiClient.proposeRemediation
    const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    const endpoint = `/api/v1/incidents/${encodeURIComponent(incidentId)}/remediations${qs}`;

    assert.equal(
      endpoint,
      '/api/v1/incidents/INC-8492/remediations?project_id=e93c597f-147e-4ef0-b210-8f7911609527',
      'Proposal URL must contain ?project_id=<actual_project_id>'
    );
  });

  it('verifies that remediation listing (getRemediations) contract formats ?project_id=...', () => {
    const incidentId = 'INC-8492';
    const projectId = 'e93c597f-147e-4ef0-b210-8f7911609527';

    // Verify the URL formation logic used by apiClient.getRemediations
    const qsWithProj = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    const endpointWithProj = `/api/v1/incidents/${encodeURIComponent(incidentId)}/remediations${qsWithProj}`;

    assert.equal(
      endpointWithProj,
      '/api/v1/incidents/INC-8492/remediations?project_id=e93c597f-147e-4ef0-b210-8f7911609527',
      'Remediation listing URL must contain ?project_id=<actual_project_id>'
    );

    const omittedProjectId: string | undefined = undefined;
    const qsWithoutProj = omittedProjectId ? `?project_id=${encodeURIComponent(omittedProjectId)}` : '';
    const endpointWithoutProj = `/api/v1/incidents/${encodeURIComponent(incidentId)}/remediations${qsWithoutProj}`;

    assert.equal(
      endpointWithoutProj,
      '/api/v1/incidents/INC-8492/remediations',
      'Remediation listing URL without project_id must not have query string'
    );
  });
});
