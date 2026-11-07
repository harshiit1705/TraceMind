import { 
  DataMode, 
  ApiResponse, 
  ApiError,
  ServiceItem,
  ServicesOverviewStats,
  IncidentItem,
  IncidentsKpiStats,
  TraceItem,
  AiInvestigationSummary,
  GroundedInvestigationResponse,
  PostmortemReport,
  SystemSettings,
  TelemetryOverviewData,
  ServiceTopologyData,
  CorrelationGroup,
  RootCauseCandidate,
  ProjectItem,
} from '../types';
import { 
  MOCK_SERVICES, 
  MOCK_SERVICES_STATS,
  MOCK_INCIDENTS, 
  MOCK_INCIDENTS_KPI_STATS,
  MOCK_TELEMETRY_SERIES,
  MOCK_TOPOLOGY_DATA,
  MOCK_TRACES, 
  MOCK_INVESTIGATION, 
  MOCK_GROUNDED_INVESTIGATION,
  MOCK_POSTMORTEM, 
  MOCK_SETTINGS,
  MOCK_CORRELATION_GROUP,
  MOCK_PROJECTS,
} from '../mocks/mockData';

class ApiClient {
  private readonly dataMode: DataMode;
  private readonly baseUrl: string;

  constructor() {
    const envMode = import.meta.env.VITE_DATA_MODE as string;
    this.dataMode = envMode === 'api' ? 'api' : 'mock';
    this.baseUrl = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';
  }

  public getDataMode(): DataMode {
    return this.dataMode;
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Centralized request handler.
   * STRICT POLICY: If VITE_DATA_MODE is 'api', it connects to the FastAPI backend.
   * If the API is unreachable, it raises an explicit error and NEVER falls back to mock data.
   */
  private async request<T>(
    endpoint: string, 
    mockFallback: T, 
    options?: RequestInit
  ): Promise<ApiResponse<T>> {
    const timestamp = new Date().toISOString();

    if (this.dataMode === 'mock') {
      // Simulate minimal realistic latency for demonstration
      await new Promise(resolve => setTimeout(resolve, 60));
      return {
        data: mockFallback,
        source: 'mock',
        timestamp,
      };
    }

    // In API mode: execute remote HTTP call
    const fullUrl = `${this.baseUrl.replace(/\/$/, '')}/${endpoint.replace(/^\//, '')}`;
    try {
      const response = await fetch(fullUrl, {
        method: options?.method || 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          ...(options?.headers || {}),
        },
        body: options?.body,
      });

      if (!response.ok) {
        let errorBodyText = '';
        let errorJson: { detail?: string | Record<string, unknown> } | null = null;
        try {
          errorJson = await response.json();
        } catch {
          errorBodyText = await response.text();
        }

        const message = errorJson?.detail 
          ? (typeof errorJson.detail === 'string' ? errorJson.detail : JSON.stringify(errorJson.detail))
          : `Backend API responded with status ${response.status}: ${response.statusText}`;

        const error: ApiError = {
          message,
          status: response.status,
          code: `HTTP_${response.status}`,
          details: { 
            endpoint, 
            status: response.status,
            body: errorJson || errorBodyText,
            hint: response.status === 503 
              ? 'Gemini API key is unconfigured or provider is temporarily unavailable. Check GEMINI_API_KEY on the backend.' 
              : response.status === 504 
              ? 'Gemini investigation request timed out before synthesizing the result.'
              : undefined,
          },
        };
        throw error;
      }

      const json = await response.json();
      return {
        data: json as T,
        source: 'api',
        timestamp,
      };
    } catch (err: unknown) {
      if ((err as ApiError)?.status !== undefined) {
        throw err;
      }
      const error: ApiError = {
        message: err instanceof Error ? err.message : 'Failed to connect to backend API',
        code: 'API_CONNECTION_ERROR',
        details: {
          baseUrl: this.baseUrl,
          endpoint,
          hint: 'TraceMind is operating in explicit API mode (VITE_DATA_MODE=api). Please verify your FastAPI backend is running.',
        },
      };
      throw error;
    }
  }

  // --- Domain Data Access Methods ---

  public async getProjects(): Promise<ApiResponse<ProjectItem[]>> {
    return this.request<ProjectItem[]>('/api/v1/projects', MOCK_PROJECTS);
  }

  public async getTelemetryOverview(timeRange: '15m' | '1h' | '24h' = '15m'): Promise<ApiResponse<TelemetryOverviewData>> {
    const fallback = MOCK_TELEMETRY_SERIES[timeRange] || MOCK_TELEMETRY_SERIES['15m'];
    return this.request<TelemetryOverviewData>(`/api/v1/telemetry/overview?range=${timeRange}`, fallback);
  }

  public async getServices(): Promise<ApiResponse<ServiceItem[]>> {
    return this.request<ServiceItem[]>('/api/v1/services', MOCK_SERVICES);
  }

  public async getServicesOverviewStats(): Promise<ApiResponse<ServicesOverviewStats>> {
    return this.request<ServicesOverviewStats>('/api/v1/services/stats', MOCK_SERVICES_STATS);
  }

  public async getServiceById(id: string): Promise<ApiResponse<ServiceItem | null>> {
    const mock = MOCK_SERVICES.find(s => s.id === id || s.identifier === id || s.name.toLowerCase() === id.toLowerCase()) || null;
    return this.request<ServiceItem | null>(`/api/v1/services/${id}`, mock);
  }

  public async getTopology(): Promise<ApiResponse<ServiceTopologyData>> {
    return this.request<ServiceTopologyData>('/api/v1/topology', MOCK_TOPOLOGY_DATA);
  }

  public async getIncidents(): Promise<ApiResponse<IncidentItem[]>> {
    return this.request<IncidentItem[]>('/api/v1/incidents', MOCK_INCIDENTS);
  }

  public async getIncidentsKpiStats(): Promise<ApiResponse<IncidentsKpiStats>> {
    return this.request<IncidentsKpiStats>('/api/v1/incidents/stats', MOCK_INCIDENTS_KPI_STATS);
  }

  public async getIncidentById(id: string): Promise<ApiResponse<IncidentItem | null>> {
    const mock = MOCK_INCIDENTS.find(inc => inc.id.toLowerCase() === id.toLowerCase()) || MOCK_INCIDENTS[0];
    return this.request<IncidentItem | null>(`/api/v1/incidents/${id}`, mock);
  }

  public async getTraces(): Promise<ApiResponse<TraceItem[]>> {
    return this.request<TraceItem[]>('/api/v1/traces', MOCK_TRACES);
  }

  /**
   * Retrieves an investigation by its UUID (or legacy ID).
   * Supports both GroundedInvestigationResponse and legacy AiInvestigationSummary.
   */
  public async getInvestigation(
    id?: string
  ): Promise<ApiResponse<GroundedInvestigationResponse | AiInvestigationSummary>> {
    if (!id) {
      return {
        data: MOCK_GROUNDED_INVESTIGATION,
        source: this.dataMode,
        timestamp: new Date().toISOString(),
      };
    }
    const fallback = id.startsWith('INC-') || id.includes('demo') 
      ? MOCK_INVESTIGATION 
      : MOCK_GROUNDED_INVESTIGATION;
    return this.request<GroundedInvestigationResponse | AiInvestigationSummary>(
      `/api/v1/investigations/${id}`,
      fallback
    );
  }

  /**
   * Generates or idempotently reuses a grounded Gemini AI incident investigation for a correlation group.
   */
  public async generateInvestigation(
    correlationGroupId: string,
    forceRegenerate: boolean = false
  ): Promise<ApiResponse<GroundedInvestigationResponse>> {
    return this.request<GroundedInvestigationResponse>(
      '/api/v1/investigations/generate',
      MOCK_GROUNDED_INVESTIGATION,
      {
        method: 'POST',
        body: JSON.stringify({
          correlation_group_id: correlationGroupId,
          force_regenerate: forceRegenerate,
        }),
      }
    );
  }

  /**
   * Retrieves a grounded investigation by UUID via GET /api/v1/investigations/{id}.
   */
  public async getGroundedInvestigation(
    investigationId: string
  ): Promise<ApiResponse<GroundedInvestigationResponse>> {
    return this.request<GroundedInvestigationResponse>(
      `/api/v1/investigations/${investigationId}`,
      MOCK_GROUNDED_INVESTIGATION
    );
  }

  /**
   * Strictly read-only retrieval of the latest persisted investigation for a correlation group.
   * Queries GET /api/v1/correlations/{correlation_group_id}/investigation.
   * Never triggers Gemini generation or creates database records.
   * Returns null if no investigation exists for the group.
   */
  public async getInvestigationByCorrelationGroup(
    correlationGroupId: string
  ): Promise<ApiResponse<GroundedInvestigationResponse | null>> {
    const fallback = correlationGroupId === MOCK_CORRELATION_GROUP.id ? MOCK_GROUNDED_INVESTIGATION : null;
    return this.request<GroundedInvestigationResponse | null>(
      `/api/v1/correlations/${correlationGroupId}/investigation`,
      fallback
    );
  }

  public async getPostmortem(incidentId?: string): Promise<ApiResponse<PostmortemReport>> {
    const endpoint = incidentId ? `/api/v1/postmortems/${incidentId}` : '/api/v1/postmortems/latest';
    return this.request<PostmortemReport>(endpoint, MOCK_POSTMORTEM);
  }

  public async getSettings(): Promise<ApiResponse<SystemSettings>> {
    return this.request<SystemSettings>('/api/v1/settings', MOCK_SETTINGS);
  }

  /**
   * Retrieves correlation groups. If projectId is not specified in API mode,
   * queries the active project list first to resolve the required project_id parameter.
   */
  public async getCorrelations(projectId?: string): Promise<ApiResponse<CorrelationGroup[]>> {
    let targetProjectId = projectId;

    if (!targetProjectId && this.dataMode === 'api') {
      try {
        const projRes = await this.getProjects();
        if (projRes.data && projRes.data.length > 0) {
          targetProjectId = projRes.data[0].id;
        }
      } catch {
        // Fall back to attempting call without project_id if project lookup fails
      }
    }

    const endpoint = targetProjectId 
      ? `/api/v1/correlations?project_id=${targetProjectId}` 
      : '/api/v1/correlations';

    return this.request<CorrelationGroup[]>(endpoint, [MOCK_CORRELATION_GROUP]);
  }

  public async getCorrelationById(id: string): Promise<ApiResponse<CorrelationGroup>> {
    return this.request<CorrelationGroup>(`/api/v1/correlations/${id}`, MOCK_CORRELATION_GROUP);
  }

  public async getRootCauseCandidates(correlationId: string): Promise<ApiResponse<RootCauseCandidate[]>> {
    return this.request<RootCauseCandidate[]>(
      `/api/v1/correlations/${correlationId}/candidates`,
      MOCK_CORRELATION_GROUP.ranked_candidates
    );
  }
}

export const apiClient = new ApiClient();
