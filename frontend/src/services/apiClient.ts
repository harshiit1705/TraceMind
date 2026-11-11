import { 
  DataMode, 
  ApiResponse, 
  ApiError,
  ServiceItem,
  ServicesOverviewStats,
  IncidentItem,
  IncidentStatus,
  IncidentEvent,
  IncidentsKpiStats,
  TraceItem,
  ApplicationLogItem,
  PaginatedLogsResponse,
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

function formatActiveDuration(startedAt?: string, endedAt?: string | null): string {
  if (!startedAt) return '0m';
  const start = new Date(startedAt).getTime();
  const end = endedAt ? new Date(endedAt).getTime() : Date.now();
  const diffSec = Math.max(0, Math.floor((end - start) / 1000));
  const mins = Math.floor(diffSec / 60);
  const secs = diffSec % 60;
  if (mins < 60) return `${mins}m ${secs}s`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `${hrs}h ${remMins}m`;
}

function mapBackendServiceToItem(raw: any): ServiceItem {
  if (!raw) return raw;
  const meta = (raw.metadata_json && typeof raw.metadata_json === 'object') ? raw.metadata_json : {};
  const tierVal = typeof raw.tier === 'number' && (raw.tier === 0 || raw.tier === 1 || raw.tier === 2) ? raw.tier : 1;
  return {
    id: String(raw.id || ''),
    name: raw.name || '',
    identifier: raw.identifier || raw.slug || '',
    tier: tierVal as ServiceItem['tier'],
    status: (raw.status || 'healthy').toLowerCase() as ServiceItem['status'],
    environment: raw.environment || 'production',
    ownerTeam: raw.ownerTeam ?? raw.owner_team ?? 'Platform',
    requestRateRps: Number(raw.requestRateRps ?? raw.request_rate_rps ?? 0),
    errorRatePercent: Number(raw.errorRatePercent ?? raw.error_rate_percent ?? 0),
    p95LatencyMs: Number(raw.p95LatencyMs ?? raw.p95_latency_ms ?? 0),
    lastSeen: raw.lastSeen ?? raw.updated_at ?? new Date().toISOString(),
    lastDeployment: raw.lastDeployment ?? raw.last_deployment ?? meta.last_deployment ?? 'Active',
    availabilityPercent: raw.availabilityPercent ?? meta.availability_percent,
    cpuSaturationPercent: raw.cpuSaturationPercent ?? raw.cpu_usage_percent ?? meta.cpu_saturation_percent,
    memoryUsagePercent: raw.memoryUsagePercent ?? raw.memory_usage_mb ?? meta.memory_usage_percent,
    upstreamDependencies: raw.upstreamDependencies ?? meta.upstream_dependencies,
    downstreamDependencies: raw.downstreamDependencies ?? meta.downstream_dependencies,
  };
}

function mapBackendIncidentToItem(raw: any): IncidentItem {
  if (!raw) return raw;
  if (raw.commander && typeof raw.commander === 'object' && raw.startedAt) {
    return raw as IncidentItem;
  }
  return {
    id: raw.incident_number || raw.id,
    title: raw.title || '',
    severity: (raw.severity || 'MEDIUM').toUpperCase() as any,
    status: (raw.status || 'DETECTED').toUpperCase() as any,
    startedAt: raw.started_at
      ? new Date(raw.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })
      : 'Just now',
    activeDuration: formatActiveDuration(raw.started_at, raw.resolved_at || raw.mitigated_at),
    commander: {
      name: raw.commander_name || 'Alex Chen',
      role: raw.commander_role || 'Staff SRE',
    },
    impactedEntities: (raw.affected_services || []).map((s: string) => ({
      name: s,
      metricSummary: 'Correlated cascade',
      status: (raw.severity === 'CRITICAL' ? 'critical' : 'degraded') as any,
    })),
    rootCauseSummary: raw.root_cause_summary || raw.summary || '',
    correlatedTracesCount: 0,
    aiRemediationAvailable: Boolean(raw.correlation_group_id),
    affectedServices: raw.affected_services || [],
    correlationGroupId: raw.correlation_group_id || null,
    correlation_group_id: raw.correlation_group_id || null,
    isDemo: Boolean(raw.is_demo),
    is_demo: Boolean(raw.is_demo),
    summary: raw.summary || '',
    mitigatedAt: raw.mitigated_at || null,
    resolvedAt: raw.resolved_at || null,
  };
}

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
    const rawRes = await this.request<any[]>('/api/v1/services', MOCK_SERVICES);
    return {
      ...rawRes,
      data: Array.isArray(rawRes.data) ? rawRes.data.map(mapBackendServiceToItem) : [],
    };
  }

  public async getServicesOverviewStats(): Promise<ApiResponse<ServicesOverviewStats>> {
    return this.request<ServicesOverviewStats>('/api/v1/services/stats', MOCK_SERVICES_STATS);
  }

  public async getServiceById(id: string): Promise<ApiResponse<ServiceItem | null>> {
    const mock = MOCK_SERVICES.find(s => s.id === id || s.identifier === id || s.name.toLowerCase() === id.toLowerCase()) || null;
    const rawRes = await this.request<any | null>(`/api/v1/services/${id}`, mock);
    return {
      ...rawRes,
      data: rawRes.data ? mapBackendServiceToItem(rawRes.data) : null,
    };
  }

  public async getTopology(projectId?: string): Promise<ApiResponse<ServiceTopologyData>> {
    if (this.dataMode !== 'api') {
      return {
        data: MOCK_TOPOLOGY_DATA,
        source: 'mock',
        timestamp: new Date().toISOString(),
      };
    }

    let targetProjectId = projectId;
    if (!targetProjectId) {
      const projRes = await this.getProjects();
      if (projRes.data && projRes.data.length > 0) {
        const defaultProj = projRes.data.find((p) => p.slug === 'core-ecommerce') || projRes.data[0];
        targetProjectId = defaultProj.id;
      }
    }

    if (!targetProjectId) {
      return {
        data: {
          nodes: [],
          edges: [],
          clustersCount: 0,
          activeEdgesCount: 0,
          propagationDepthHops: 0,
          cascadeLatencyAddedMs: 0,
        },
        source: 'api',
        timestamp: new Date().toISOString(),
      };
    }

    const [graphRes, servicesRes] = await Promise.all([
      this.request<any>(`/api/v1/dependencies/graph?project_id=${encodeURIComponent(targetProjectId)}`, null),
      this.request<any[]>(`/api/v1/services?project_id=${encodeURIComponent(targetProjectId)}`, []),
    ]);

    const svcById = new Map<string, any>();
    for (const s of servicesRes.data || []) {
      svcById.set(String(s.id), s);
    }

    const rawNodes: any[] = graphRes.data?.nodes || [];
    const rawEdges: any[] = graphRes.data?.edges || [];
    const idToSlug = new Map<string, string>();
    for (const n of rawNodes) {
      idToSlug.set(String(n.id), n.slug || String(n.id));
    }

    const nodes = rawNodes.map((n) => {
      const svc = svcById.get(String(n.id)) || {};
      const meta = (svc.metadata_json && typeof svc.metadata_json === 'object') ? svc.metadata_json : {};
      const status = String(svc.status || n.status || 'healthy').toLowerCase() as 'healthy' | 'degraded' | 'unhealthy';
      const rps = Number(svc.request_rate_rps ?? 0);
      const lat = Number(svc.p95_latency_ms ?? 0);
      const err = Number(svc.error_rate_percent ?? 0);
      return {
        id: n.slug || String(n.id),
        name: n.name || svc.name || n.slug,
        identifier: n.identifier || svc.identifier || n.slug,
        role: svc.owner_team || (String(n.identifier || '').startsWith('db:') ? 'Database' : `Tier ${n.tier ?? 1}`),
        tier: (typeof n.tier === 'number' && (n.tier === 0 || n.tier === 1 || n.tier === 2) ? n.tier : 1) as 0 | 1 | 2,
        status,
        latencyMs: lat,
        errorRatePercent: err,
        throughputStr: `${rps.toFixed(1)} req/s`,
        isAnomalous: status === 'degraded' || status === 'unhealthy',
        isRootCause: status === 'unhealthy',
        cpuSaturationPercent: meta.cpu_saturation_percent,
      };
    });

    const mapProtocol = (depType: string): 'HTTP/REST' | 'gRPC' | 'Async Event' | 'SQL' => {
      const d = (depType || '').toLowerCase();
      if (d === 'database') return 'SQL';
      if (d === 'async') return 'Async Event';
      return 'HTTP/REST';
    };

    const nodeStatusBySlug = new Map(nodes.map((n) => [n.id, n.status]));
    const edges = rawEdges.map((e) => {
      const srcSlug = idToSlug.get(String(e.source_service_id)) || String(e.source_service_id);
      const tgtSlug = idToSlug.get(String(e.target_service_id)) || String(e.target_service_id);
      const srcSt = nodeStatusBySlug.get(srcSlug);
      const tgtSt = nodeStatusBySlug.get(tgtSlug);
      return {
        id: String(e.id),
        source: srcSlug,
        target: tgtSlug,
        protocol: mapProtocol(e.dependency_type),
        isAnomalous: srcSt === 'unhealthy' || tgtSt === 'unhealthy' || (srcSt === 'degraded' && tgtSt === 'degraded'),
        label: e.description || e.dependency_type,
      };
    });

    return {
      data: {
        nodes,
        edges,
        clustersCount: nodes.length > 0 ? 1 : 0,
        activeEdgesCount: edges.length,
        propagationDepthHops: edges.length > 0 ? Math.min(edges.length, 3) : 0,
        cascadeLatencyAddedMs: nodes
          .filter((n) => n.status !== 'healthy')
          .reduce((acc, n) => Math.max(acc, n.latencyMs), 0),
      },
      source: 'api',
      timestamp: new Date().toISOString(),
    };
  }

  public async getIncidents(): Promise<ApiResponse<IncidentItem[]>> {
    const rawRes = await this.request<any>('/api/v1/incidents', MOCK_INCIDENTS);
    let itemsList: IncidentItem[] = [];
    if (Array.isArray(rawRes.data)) {
      itemsList = rawRes.data.map(mapBackendIncidentToItem);
    } else if (rawRes.data && Array.isArray(rawRes.data.items)) {
      itemsList = rawRes.data.items.map(mapBackendIncidentToItem);
    }
    return {
      ...rawRes,
      data: itemsList,
    };
  }

  public async getIncidentsKpiStats(): Promise<ApiResponse<IncidentsKpiStats>> {
    return this.request<IncidentsKpiStats>('/api/v1/incidents/stats', MOCK_INCIDENTS_KPI_STATS);
  }

  public async getIncidentById(id: string): Promise<ApiResponse<IncidentItem | null>> {
    const mock = MOCK_INCIDENTS.find(inc => inc.id.toLowerCase() === id.toLowerCase()) || MOCK_INCIDENTS[0];
    const rawRes = await this.request<any>(`/api/v1/incidents/${id}`, mock);
    return {
      ...rawRes,
      data: rawRes.data ? mapBackendIncidentToItem(rawRes.data) : null,
    };
  }

  public async updateIncidentStatus(
    incidentId: string,
    statusUpdate: { status: IncidentStatus; commander_name?: string; commander_role?: string; comment?: string }
  ): Promise<ApiResponse<IncidentItem>> {
    const rawRes = await this.request<any>(
      `/api/v1/incidents/${incidentId}/status`,
      null,
      {
        method: 'PATCH',
        body: JSON.stringify(statusUpdate),
      }
    );
    return {
      ...rawRes,
      data: mapBackendIncidentToItem(rawRes.data),
    };
  }

  public async getIncidentTimeline(incidentId: string): Promise<ApiResponse<IncidentEvent[]>> {
    const rawRes = await this.request<{ events?: any[] }>(`/api/v1/incidents/${incidentId}/timeline`, { events: [] });
    const rawEvents = rawRes.data?.events || [];
    const formattedEvents: IncidentEvent[] = rawEvents.map((e: any) => ({
      id: e.id || String(Math.random()),
      timestamp: e.timestamp || new Date().toISOString(),
      relativeTime: e.timestamp ? new Date(e.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'recently',
      title: e.title || '',
      source: e.source || 'system',
      description: e.description || '',
      type: (e.event_type || 'anomaly') as any,
    }));
    return {
      ...rawRes,
      data: formattedEvents,
    };
  }

  public async getTraces(params?: {
    service?: string;
    status?: string;
    minDurationMs?: number;
    traceId?: string;
    limit?: number;
    offset?: number;
  }): Promise<ApiResponse<TraceItem[]>> {
    const paged = await this.getTracesPaginated(params);
    return {
      data: paged.data.items,
      source: paged.source,
      timestamp: paged.timestamp,
    };
  }

  public async getTracesPaginated(params?: {
    service?: string;
    status?: string;
    minDurationMs?: number;
    traceId?: string;
    limit?: number;
    offset?: number;
  }): Promise<ApiResponse<{ items: TraceItem[]; total: number; page: number; page_size: number; total_pages: number }>> {
    const qs = new URLSearchParams();
    if (params?.service) qs.set('service', params.service);
    if (params?.status) qs.set('status', params.status);
    if (params?.minDurationMs !== undefined) qs.set('min_duration_ms', String(params.minDurationMs));
    if (params?.traceId) qs.set('trace_id', params.traceId);
    if (params?.limit !== undefined) qs.set('limit', String(params.limit));
    if (params?.offset !== undefined) qs.set('offset', String(params.offset));
    const queryStr = qs.toString();
    const endpoint = queryStr ? `/api/v1/traces?${queryStr}` : '/api/v1/traces';

    const mockFallback = {
      items: MOCK_TRACES,
      total: MOCK_TRACES.length,
      page: 1,
      page_size: params?.limit ?? 20,
      total_pages: 1,
    };

    const rawRes = await this.request<any>(endpoint, mockFallback);
    if (Array.isArray(rawRes.data)) {
      return {
        ...rawRes,
        data: {
          items: rawRes.data,
          total: rawRes.data.length,
          page: 1,
          page_size: rawRes.data.length || 20,
          total_pages: 1,
        },
      };
    }
    return {
      ...rawRes,
      data: {
        items: rawRes.data?.items || [],
        total: rawRes.data?.total ?? 0,
        page: rawRes.data?.page ?? 1,
        page_size: rawRes.data?.page_size ?? 20,
        total_pages: rawRes.data?.total_pages ?? 1,
      },
    };
  }

  public async getTraceById(traceId: string): Promise<ApiResponse<TraceItem | null>> {
    const mock = MOCK_TRACES.find(t => t.id === traceId) || MOCK_TRACES[0] || null;
    return this.request<TraceItem | null>(`/api/v1/traces/${encodeURIComponent(traceId)}`, mock);
  }

  public async getLogs(params?: {
    service?: string;
    level?: string;
    search?: string;
    trace_id?: string;
    request_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<ApiResponse<PaginatedLogsResponse>> {
    const qs = new URLSearchParams();
    if (params?.service) qs.set('service', params.service);
    if (params?.level) qs.set('level', params.level);
    if (params?.search) qs.set('search', params.search);
    if (params?.trace_id) qs.set('trace_id', params.trace_id);
    if (params?.request_id) qs.set('request_id', params.request_id);
    if (params?.limit !== undefined) qs.set('limit', String(params.limit));
    if (params?.offset !== undefined) qs.set('offset', String(params.offset));
    const queryStr = qs.toString();
    const endpoint = queryStr ? `/api/v1/logs?${queryStr}` : '/api/v1/logs';

    const emptyFallback: PaginatedLogsResponse = {
      items: [],
      total: 0,
      page: 1,
      page_size: params?.limit ?? 50,
      total_pages: 1,
    };
    return this.request<PaginatedLogsResponse>(endpoint, emptyFallback);
  }

  public async getIncidentLogs(incidentId: string, limit: number = 50): Promise<ApiResponse<ApplicationLogItem[]>> {
    const rawRes = await this.request<any>(
      `/api/v1/incidents/${encodeURIComponent(incidentId)}/logs?limit=${limit}`,
      { items: [] }
    );
    const itemsList: ApplicationLogItem[] = Array.isArray(rawRes.data)
      ? rawRes.data
      : (rawRes.data?.items || []);
    return {
      ...rawRes,
      data: itemsList,
    };
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
