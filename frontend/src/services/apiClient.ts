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
  PostmortemReport,
  SystemSettings,
  TelemetryOverviewData,
  ServiceTopologyData
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
  MOCK_POSTMORTEM, 
  MOCK_SETTINGS 
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
  private async request<T>(endpoint: string, mockFallback: T): Promise<ApiResponse<T>> {
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
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
      });

      if (!response.ok) {
        const errorBody = await response.text();
        const error: ApiError = {
          message: `Backend API responded with status ${response.status}: ${response.statusText}`,
          status: response.status,
          details: { endpoint, body: errorBody },
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
      // STRICT REQUIREMENT: Never silently fall back to mock data!
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

  public async getInvestigation(incidentId?: string): Promise<ApiResponse<AiInvestigationSummary>> {
    const endpoint = incidentId ? `/api/v1/investigations/${incidentId}` : '/api/v1/investigations/latest';
    return this.request<AiInvestigationSummary>(endpoint, MOCK_INVESTIGATION);
  }

  public async getPostmortem(incidentId?: string): Promise<ApiResponse<PostmortemReport>> {
    const endpoint = incidentId ? `/api/v1/postmortems/${incidentId}` : '/api/v1/postmortems/latest';
    return this.request<PostmortemReport>(endpoint, MOCK_POSTMORTEM);
  }

  public async getSettings(): Promise<ApiResponse<SystemSettings>> {
    return this.request<SystemSettings>('/api/v1/settings', MOCK_SETTINGS);
  }
}

export const apiClient = new ApiClient();
