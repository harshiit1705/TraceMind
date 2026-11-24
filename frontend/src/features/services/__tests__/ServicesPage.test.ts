import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { executeIncidentCorrelation } from '../correlationHandler.ts';
import type { ServiceItem, CorrelationEvaluationResponse, ApiResponse } from '../../../types';
import type { apiClient } from '../../../services/apiClient';

describe('Payment Service Detail Panel - Anomaly Correlation', () => {
  const dummyPaymentService: ServiceItem = {
    id: 'svc-payment-1',
    name: 'Payment Service',
    identifier: 'payment-service',
    tier: 1,
    status: 'degraded',
    environment: 'production',
    ownerTeam: 'Checkout & Payments',
    requestRateRps: 120.5,
    errorRatePercent: 100.0,
    p95LatencyMs: 450.2,
    lastSeen: new Date().toISOString(),
    projectId: 'e93c597f-147e-4ef0-b210-8f7911609527',
    project_id: 'e93c597f-147e-4ef0-b210-8f7911609527',
  };

  it('calls correlateIncidents API with the correct project ID from selectedService', async () => {
    let capturedPayload: any = null;
    let navigatedPath = '';
    const loadingStates: boolean[] = [];
    let feedback: { type: 'success' | 'warning' | 'error'; message: string } | null = null;

    const mockApi = {
      correlateIncidents: async (payload: any) => {
        capturedPayload = payload;
        return {
          data: {
            project_id: payload.project_id,
            evaluated_at: new Date().toISOString(),
            time_window_start: new Date().toISOString(),
            time_window_end: new Date().toISOString(),
            total_anomalies_evaluated: 5,
            correlation_groups_count: 2,
            groups: [],
          },
          source: 'api',
          timestamp: new Date().toISOString(),
        } as ApiResponse<CorrelationEvaluationResponse>;
      },
      getProjects: async () => ({ data: [] } as any),
    } as unknown as typeof apiClient;

    const success = await executeIncidentCorrelation({
      selectedService: dummyPaymentService,
      services: [dummyPaymentService],
      api: mockApi,
      navigate: (path: string) => { navigatedPath = path; },
      setIsCorrelating: (loading: boolean) => { loadingStates.push(loading); },
      setFeedback: (f) => { feedback = f; },
    });

    assert.equal(success, true);
    assert.ok(capturedPayload, 'API should have been called');
    assert.equal(capturedPayload.project_id, 'e93c597f-147e-4ef0-b210-8f7911609527');
    assert.equal(navigatedPath, '/incidents');
    assert.ok(feedback);
    assert.equal(loadingStates.length, 2);
  });

  it('resolves project ID dynamically via getProjects when service has no direct projectId', async () => {
    const serviceWithoutProj: ServiceItem = {
      ...dummyPaymentService,
      projectId: undefined,
      project_id: undefined,
    };

    let capturedPayload: any = null;
    let getProjectsCalled = false;
    let navigatedPath = '';

    const mockApi = {
      getProjects: async () => {
        getProjectsCalled = true;
        return {
          data: [
            { id: 'proj-other-1', name: 'Other Service', slug: 'other-service', environment: 'production' },
            { id: 'dynamic-core-ecom-id', name: 'Core E-Commerce & Payments', slug: 'core-ecommerce', environment: 'production' },
          ],
          source: 'api',
          timestamp: new Date().toISOString(),
        } as any;
      },
      correlateIncidents: async (payload: any) => {
        capturedPayload = payload;
        return {
          data: {
            project_id: payload.project_id,
            evaluated_at: new Date().toISOString(),
            time_window_start: new Date().toISOString(),
            time_window_end: new Date().toISOString(),
            total_anomalies_evaluated: 2,
            correlation_groups_count: 1,
            groups: [],
          },
          source: 'api',
          timestamp: new Date().toISOString(),
        } as ApiResponse<CorrelationEvaluationResponse>;
      },
    } as unknown as typeof apiClient;

    const success = await executeIncidentCorrelation({
      selectedService: serviceWithoutProj,
      services: [serviceWithoutProj],
      api: mockApi,
      navigate: (path: string) => { navigatedPath = path; },
      setIsCorrelating: () => {},
      setFeedback: () => {},
    });

    assert.equal(success, true);
    assert.equal(getProjectsCalled, true, 'Should query getProjects to resolve project');
    assert.equal(capturedPayload.project_id, 'dynamic-core-ecom-id', 'Should select preferred core-ecommerce project');
    assert.equal(navigatedPath, '/incidents');
  });

  it('manages loading state correctly to prevent duplicate submissions', async () => {
    let callCount = 0;
    const loadingStates: boolean[] = [];

    const mockApi = {
      correlateIncidents: async (payload: any) => {
        callCount++;
        // Simulate async in-flight delay
        await new Promise((r) => setTimeout(r, 20));
        return {
          data: {
            project_id: payload.project_id,
            evaluated_at: new Date().toISOString(),
            time_window_start: new Date().toISOString(),
            time_window_end: new Date().toISOString(),
            total_anomalies_evaluated: 1,
            correlation_groups_count: 1,
            groups: [],
          },
          source: 'api',
          timestamp: new Date().toISOString(),
        } as ApiResponse<CorrelationEvaluationResponse>;
      },
      getProjects: async () => ({ data: [] } as any),
    } as unknown as typeof apiClient;

    // Simulate in-flight protection exactly as implemented in ServicesPage.handleCorrelateIncidents
    let isCorrelating = false;
    const trigger = async () => {
      if (isCorrelating) return false;
      return executeIncidentCorrelation({
        selectedService: dummyPaymentService,
        services: [dummyPaymentService],
        api: mockApi,
        navigate: () => {},
        setIsCorrelating: (loading) => {
          isCorrelating = loading;
          loadingStates.push(loading);
        },
        setFeedback: () => {},
      });
    };

    // First call starts
    const p1 = trigger();
    // Second concurrent call immediately rejected by isCorrelating guard
    const p2 = trigger();

    const [r1, r2] = await Promise.all([p1, p2]);

    assert.equal(r1, true, 'First invocation should complete successfully');
    assert.equal(r2, false, 'Second invocation should be blocked while first is in-flight');
    assert.equal(callCount, 1, 'API should only be called once');
    assert.deepEqual(loadingStates, [true, false], 'Loading state should transition true -> false');
  });

  it('displays actual evaluation result upon successful evaluation', async () => {
    let feedback: { type: 'success' | 'warning' | 'error'; message: string } | null = null;

    const mockApi = {
      correlateIncidents: async (payload: any) => ({
        data: {
          project_id: payload.project_id,
          evaluated_at: new Date().toISOString(),
          time_window_start: new Date().toISOString(),
          time_window_end: new Date().toISOString(),
          total_anomalies_evaluated: 7,
          correlation_groups_count: 3,
          groups: [],
        },
        source: 'api',
        timestamp: new Date().toISOString(),
      } as ApiResponse<CorrelationEvaluationResponse>),
      getProjects: async () => ({ data: [] } as any),
    } as unknown as typeof apiClient;

    await executeIncidentCorrelation({
      selectedService: dummyPaymentService,
      services: [dummyPaymentService],
      api: mockApi,
      navigate: () => {},
      setIsCorrelating: () => {},
      setFeedback: (f) => { feedback = f; },
    });

    assert.ok(feedback, 'Feedback must be set');
    const safeFeedback: { type: 'success' | 'warning' | 'error'; message: string } = feedback;
    assert.equal(safeFeedback.type, 'success');
    assert.match(safeFeedback.message, /3 group\(s\) identified across 7 anomaly event\(s\)/);
  });

  it('navigates to /incidents only upon successful evaluation', async () => {
    let navigatedPath = '';

    const mockApi = {
      correlateIncidents: async (payload: any) => ({
        data: {
          project_id: payload.project_id,
          evaluated_at: new Date().toISOString(),
          time_window_start: new Date().toISOString(),
          time_window_end: new Date().toISOString(),
          total_anomalies_evaluated: 2,
          correlation_groups_count: 1,
          groups: [],
        },
        source: 'api',
        timestamp: new Date().toISOString(),
      } as ApiResponse<CorrelationEvaluationResponse>),
      getProjects: async () => ({ data: [] } as any),
    } as unknown as typeof apiClient;

    await executeIncidentCorrelation({
      selectedService: dummyPaymentService,
      services: [dummyPaymentService],
      api: mockApi,
      navigate: (path: string) => { navigatedPath = path; },
      setIsCorrelating: () => {},
      setFeedback: () => {},
    });

    assert.equal(navigatedPath, '/incidents', 'Should navigate to /incidents upon success');
  });

  it('displays an error notification and does NOT navigate or report success when API fails', async () => {
    let navigatedPath = '';
    let feedback: { type: 'success' | 'warning' | 'error'; message: string } | null = null;

    const mockApi = {
      correlateIncidents: async () => {
        throw new Error('Project correlation failed: database timeout');
      },
      getProjects: async () => ({ data: [] } as any),
    } as unknown as typeof apiClient;

    const success = await executeIncidentCorrelation({
      selectedService: dummyPaymentService,
      services: [dummyPaymentService],
      api: mockApi,
      navigate: (path: string) => { navigatedPath = path; },
      setIsCorrelating: () => {},
      setFeedback: (f) => { feedback = f; },
    });

    assert.equal(success, false, 'Should return false on failure');
    assert.equal(navigatedPath, '', 'Must NOT navigate to /incidents on error');
    assert.ok(feedback, 'Feedback must be provided');
    const safeFeedback: { type: 'success' | 'warning' | 'error'; message: string } = feedback;
    assert.equal(safeFeedback.type, 'error');
    assert.equal(safeFeedback.message, 'Project correlation failed: database timeout');
  });


  it('does not navigate or report success when the evaluation finds no correlation groups', async () => {
    let navigatedPath = '';
    let feedback: { type: 'success' | 'warning' | 'error'; message: string } | null = null;

    const mockApi = {
      correlateIncidents: async (payload: any) => ({
        data: {
          project_id: payload.project_id,
          evaluated_at: new Date().toISOString(),
          time_window_start: new Date(Date.now() - 300000).toISOString(),
          time_window_end: new Date().toISOString(),
          total_anomalies_evaluated: 0,
          correlation_groups_count: 0,
          groups: [],
        },
        source: 'api',
        timestamp: new Date().toISOString(),
      } as ApiResponse<CorrelationEvaluationResponse>),
      getProjects: async () => ({ data: [] } as any),
    } as unknown as typeof apiClient;

    const success = await executeIncidentCorrelation({
      selectedService: dummyPaymentService,
      services: [dummyPaymentService],
      api: mockApi,
      navigate: (path: string) => { navigatedPath = path; },
      setIsCorrelating: () => {},
      setFeedback: (value) => { feedback = value; },
    });

    assert.equal(success, false);
    assert.equal(navigatedPath, '');
    assert.ok(feedback);
    const safeFeedback: { type: string; message: string } = feedback;
    assert.equal(safeFeedback.type, 'warning');
    assert.match(safeFeedback.message, /No anomaly events were found/);
    assert.match(safeFeedback.message, /No incident was created/);
  });
});
