import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, LoadingSpinner, ErrorState } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { 
  CorrelationGroup, 
  RootCauseCandidate,
  GroundedInvestigationResponse,
  AiInvestigationSummary,
  InvestigationResult,
} from '../../types';

export const AiInvestigationPage: React.FC = () => {
  const { id: routeId } = useParams<{ id: string }>();
  const navigate = useNavigate();

  // Correlation & Investigation state
  const [correlations, setCorrelations] = useState<CorrelationGroup[]>([]);
  const [selectedCorrelation, setSelectedCorrelation] = useState<CorrelationGroup | null>(null);
  const [investigation, setInvestigation] = useState<GroundedInvestigationResponse | null>(null);
  const [legacyInvestigation, setLegacyInvestigation] = useState<AiInvestigationSummary | null>(null);

  // Status & Lifecycle
  const [loading, setLoading] = useState<boolean>(true);
  const [generating, setGenerating] = useState<boolean>(false);
  const [recalculating, setRecalculating] = useState<boolean>(false);
  const [error, setError] = useState<{ message: string; details?: Record<string, unknown> } | null>(null);

  // Helper: Determine if the active investigation is a legacy Phase 2.1 demo
  const isLegacyDemo = useMemo(() => {
    if (legacyInvestigation) return true;
    if (routeId?.startsWith('INC-') || routeId?.toLowerCase().includes('demo')) return true;
    if (investigation?.is_demo === true && !investigation.result) return true;
    return false;
  }, [legacyInvestigation, investigation, routeId]);

  // Load correlations and initial investigation data
  const loadData = useCallback(async (targetCorrelationId?: string) => {
    setLoading(true);
    setError(null);

    try {
      // 1. Fetch available correlation groups
      const corrRes = await apiClient.getCorrelations();
      const groups = corrRes.data || [];
      setCorrelations(groups);

      let activeGroup: CorrelationGroup | null = null;

      // If routeId is provided, check if it matches a correlation group directly
      if (routeId && !routeId.startsWith('INC-') && !routeId.toLowerCase().includes('demo')) {
        activeGroup = groups.find((g) => g.id === routeId) || null;
        if (!activeGroup) {
          try {
            // Attempt fetching correlation group by id in case it wasn't in top list
            const singleCorr = await apiClient.getCorrelationById(routeId);
            activeGroup = singleCorr.data;
          } catch {
            // routeId is an investigation ID or legacy incident ID
          }
        }
      }

      if (!activeGroup && targetCorrelationId) {
        activeGroup = groups.find((g) => g.id === targetCorrelationId) || null;
      }

      // Default to the first available correlation group ONLY if no routeId was specified
      if (!routeId && !activeGroup && groups.length > 0) {
        activeGroup = groups[0];
      }

      setSelectedCorrelation(activeGroup);

      // 2. Fetch or resolve the investigation record
      if (routeId && !activeGroup) {
        // routeId is an investigation ID or legacy incident ID
        if (routeId.startsWith('INC-') || routeId.toLowerCase().includes('demo')) {
          try {
            const incRes = await apiClient.getIncidentById(routeId);
            setLegacyInvestigation({
              id: routeId,
              incidentId: routeId,
              agentName: "Autonomous Agent #4",
              status: "Analysis Complete",
              elapsedTime: "4m 12s",
              correlationScope: 42,
              spansAnalyzed: 128400,
              confidenceScore: 94,
              rootCauseTitle: incRes.data?.title ? `Root Cause: ${incRes.data.title}` : `Root Cause Investigation: ${routeId}`,
              rootCauseDescription: incRes.data?.rootCauseSummary || "Simulated demo investigation",
              propagationGraph: [],
              evidence: [],
              hypotheses: [],
              remediations: [],
              is_demo: true,
            });
            setInvestigation(null);
            setError(null);
          } catch {
            setLegacyInvestigation({
              id: routeId,
              incidentId: routeId,
              agentName: "Autonomous Agent #4",
              status: "Analysis Complete",
              elapsedTime: "4m 12s",
              correlationScope: 42,
              spansAnalyzed: 128400,
              confidenceScore: 94,
              rootCauseTitle: `Root Cause Investigation: ${routeId}`,
              rootCauseDescription: "Simulated demonstration incident from Phase 2.1 catalog.",
              propagationGraph: [],
              evidence: [],
              hypotheses: [],
              remediations: [],
              is_demo: true,
            });
            setInvestigation(null);
            setError(null);
          }
        } else {
          try {
            const invRes = await apiClient.getInvestigation(routeId);
            const data = invRes.data;
            if (data && 'prompt_version' in data) {
              setInvestigation(data as GroundedInvestigationResponse);
              setLegacyInvestigation(null);
              // If linked to a correlation group, load that correlation group
              const cid = (data as GroundedInvestigationResponse).correlation_group_id;
              if (cid) {
                const matchedGroup = groups.find((g) => g.id === cid);
                if (matchedGroup) {
                  setSelectedCorrelation(matchedGroup);
                } else {
                  try {
                    const grpRes = await apiClient.getCorrelationById(cid);
                    setSelectedCorrelation(grpRes.data);
                  } catch {
                    // Keep whatever is available
                  }
                }
              }
            } else {
              // Legacy demo investigation
              setLegacyInvestigation(data as AiInvestigationSummary);
              setInvestigation(null);
            }
          } catch (invErr: unknown) {
            const e = invErr as { message?: string; details?: Record<string, unknown> };
            setError({
              message: e.message || 'Investigation record could not be loaded.',
              details: e.details,
            });
          }
        }
      } else if (activeGroup) {
        // Strictly read-only check for existing persisted investigation for this correlation group.
        // Never triggers Gemini generation or creates database records on page load!
        try {
          const invRes = await apiClient.getInvestigationByCorrelationGroup(activeGroup.id);
          const invData = invRes.data;
          setInvestigation(invData);
          setLegacyInvestigation(null);

          if (invData && invData.status === 'FAILED') {
            setError({
              message: invData.error_message || 'Previous investigation attempt failed. Click Retry to re-run analysis.',
              details: { status: invData.status, provider: invData.provider },
            });
          } else {
            setError(null);
          }
        } catch (fetchErr: unknown) {
          const e = fetchErr as { message?: string; status?: number; details?: Record<string, unknown> };
          setError({
            message: e.message || 'Failed to check correlation group investigation status.',
            details: e.details,
          });
          setInvestigation(null);
        }
      } else {
        setInvestigation(null);
        setLegacyInvestigation(null);
      }
    } catch (err: unknown) {
      const e = err as { message?: string; details?: Record<string, unknown> };
      setError({
        message: e.message || 'Failed to initialize AI Investigation Center',
        details: e.details,
      });
    } finally {
      setLoading(false);
    }
  }, [routeId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Switch active correlation group
  const handleSelectCorrelation = (group: CorrelationGroup) => {
    setSelectedCorrelation(group);
    setInvestigation(null);
    setLegacyInvestigation(null);
    setError(null);
    navigate(`/ai-investigations/${group.id}`);
  };

  const isGeneratingRef = useRef<boolean>(false);

  // Generate or re-generate investigation
  const handleTriggerInvestigation = async (forceRegenerate: boolean = false) => {
    if (!selectedCorrelation || isGeneratingRef.current || generating) return;

    isGeneratingRef.current = true;
    setGenerating(true);
    setError(null);

    try {
      const res = await apiClient.generateInvestigation(selectedCorrelation.id, forceRegenerate);
      setInvestigation(res.data);
      setLegacyInvestigation(null);
    } catch (err: unknown) {
      const e = err as { message?: string; status?: number; details?: Record<string, unknown> };
      setError({
        message: e.message || 'Investigation synthesis failed',
        details: e.details,
      });
    } finally {
      isGeneratingRef.current = false;
      setGenerating(false);
    }
  };

  // Recalculate multi-signal deterministic correlation & RCA
  const handleRecalculateRca = async () => {
    if (!selectedCorrelation || recalculating) return;
    setRecalculating(true);
    setError(null);
    try {
      const res = await apiClient.recalculateCorrelation(selectedCorrelation.id);
      setSelectedCorrelation(res.data);
      setCorrelations((prev) => prev.map((g) => (g.id === res.data.id ? res.data : g)));
    } catch (err: unknown) {
      const e = err as { message?: string; details?: Record<string, unknown> };
      setError({
        message: e.message || 'Multi-signal RCA recalculation failed',
        details: e.details,
      });
    } finally {
      setRecalculating(false);
    }
  };

  // Persisted Grounded Investigation Result
  const result: InvestigationResult | null = useMemo(() => {
    if (!investigation) return null;
    return investigation.result || investigation.investigation_json || null;
  }, [investigation]);

  if (loading) {
    return (
      <div className="w-full px-margin-desktop py-margin-desktop">
        <LoadingSpinner message="Correlating distributed telemetry and retrieving grounded investigation..." />
      </div>
    );
  }

  return (
    <div className="w-full px-margin-desktop py-margin-desktop">
      <div className="flex flex-col w-full gap-space-lg">
        {/* Page Header */}
        <PageHeader
          category="AI Investigation Center"
          categoryBadge={
            <div className="flex items-center gap-1.5 flex-wrap">
              {isLegacyDemo ? (
                <>
                  <span className="text-secondary font-mono-badge font-medium">
                    {legacyInvestigation?.id || 'INC-8492'}
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-900 font-mono-badge text-mono-badge uppercase font-semibold">
                    Simulated Demo (Phase 2.1)
                  </span>
                </>
              ) : (
                <>
                  <span className="text-primary font-mono-badge font-semibold">
                    {investigation?.id ? `INV-${investigation.id.slice(0, 8).toUpperCase()}` : (selectedCorrelation?.correlation_key.slice(0, 10).toUpperCase() || 'NEW')}
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-primary-fixed text-on-primary-fixed-variant font-mono-badge text-mono-badge uppercase tracking-wider font-semibold">
                    {investigation?.model_name ? `Gemini (${investigation.model_name})` : 'Google Gemini Flash'}
                  </span>
                  {investigation?.status && (
                    <span className={`px-1.5 py-0.5 rounded font-mono-badge text-mono-badge font-semibold uppercase ${
                      investigation.status === 'COMPLETED' 
                        ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' 
                        : investigation.status === 'FAILED'
                        ? 'bg-error-container text-on-error-container'
                        : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                    }`}>
                      {investigation.status}
                    </span>
                  )}
                </>
              )}
            </div>
          }
          title={
            isLegacyDemo
              ? legacyInvestigation?.rootCauseTitle || 'Simulated Incident: Aurora DB Connection Saturation'
              : result?.root_cause_analysis?.service_name
              ? `AI Root Cause Investigation: ${result.root_cause_analysis.service_name}`
              : selectedCorrelation?.summary
              ? `Anomaly Correlation Cascade: ${selectedCorrelation.summary}`
              : 'Distributed Incident Investigation'
          }
          subtitle={`Telemetry Confidence: ${selectedCorrelation ? Math.round(selectedCorrelation.confidence_score * 100) : (investigation ? 95 : 94)}% • ${selectedCorrelation?.events_count || 3} cross-service anomalies correlated • Topology ${selectedCorrelation?.topology_complete ? 'Verified DAG' : 'Unmapped'}${investigation?.latency_ms ? ` • Provider Latency: ${investigation.latency_ms}ms` : ''}`}
          actions={
            <div className="flex items-center gap-2 flex-wrap">
              {selectedCorrelation && (
                <Button 
                  variant="primary" 
                  icon={
                    generating ? 'hourglass_top' : 
                    investigation?.status === 'RUNNING' || investigation?.status === 'PENDING' ? 'hourglass_top' :
                    investigation?.status === 'FAILED' ? 'replay' :
                    investigation?.status === 'COMPLETED' ? 'replay' : 'auto_awesome'
                  }
                  disabled={generating || investigation?.status === 'RUNNING' || investigation?.status === 'PENDING'}
                  onClick={() => handleTriggerInvestigation(Boolean(investigation))}
                >
                  {
                    generating ? 'Analyzing with Gemini...' :
                    investigation?.status === 'RUNNING' || investigation?.status === 'PENDING' ? 'Analysis In Progress...' :
                    investigation?.status === 'FAILED' ? 'Retry Analysis' :
                    investigation?.status === 'COMPLETED' ? 'Re-run Analysis' :
                    'Run Gemini Investigation'
                  }
                </Button>
              )}
              <Button 
                variant="surface" 
                icon="refresh" 
                disabled={generating}
                onClick={() => loadData(selectedCorrelation?.id)}
              >
                Refresh
              </Button>
            </div>
          }
        />

        {/* Real Correlation Group Selector Bar */}
        {correlations.length > 0 && (
          <div className="p-space-md rounded-xl bg-surface-container-low border border-outline-variant/30 flex flex-col md:flex-row md:items-center justify-between gap-space-md">
            <div className="flex items-center gap-space-sm flex-wrap">
              <div className="flex items-center gap-1.5 text-xs text-secondary font-mono-badge font-semibold uppercase">
                <span className="material-symbols-outlined text-[16px] text-primary">hub</span>
                <span>Correlation Groups ({correlations.length}):</span>
              </div>
              <div className="flex items-center gap-1.5 flex-wrap">
                {correlations.map((grp) => {
                  const isSelected = selectedCorrelation?.id === grp.id;
                  return (
                    <button
                      key={grp.id}
                      onClick={() => handleSelectCorrelation(grp)}
                      className={`px-2.5 py-1 rounded-lg text-xs font-mono-caption transition-all flex items-center gap-1.5 border ${
                        isSelected
                          ? 'bg-primary text-on-primary border-primary shadow-xs font-semibold'
                          : 'bg-surface-container-lowest text-on-surface border-outline-variant/30 hover:border-primary/50'
                      }`}
                    >
                      <span className="truncate max-w-[140px]">
                        {grp.summary ? grp.summary.slice(0, 28) + '...' : grp.correlation_key.slice(0, 8)}
                      </span>
                      <span className={`px-1 py-0.2 rounded text-[10px] ${
                        isSelected ? 'bg-primary-container text-on-primary-container' : 'bg-surface-container text-secondary'
                      }`}>
                        {grp.events_count} ev
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {selectedCorrelation && (
              <div className="text-xs text-secondary font-mono-caption shrink-0">
                Window: {new Date(selectedCorrelation.time_window_start).toLocaleTimeString()} – {new Date(selectedCorrelation.time_window_end).toLocaleTimeString()}
              </div>
            )}
          </div>
        )}

        {/* Distinct Legacy Demo Disclaimer Notice */}
        {isLegacyDemo && (
          <div className="p-space-md rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-start gap-space-md">
            <div className="w-8 h-8 rounded-lg bg-amber-500/20 text-amber-800 dark:text-amber-200 flex items-center justify-center shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-[18px]">info</span>
            </div>
            <div className="flex flex-col gap-1 text-xs">
              <div className="font-semibold text-amber-900 dark:text-amber-200 uppercase tracking-wider font-mono-badge">
                Phase 2.1 Demo Incident (Non-Grounded)
              </div>
              <p className="text-amber-800 dark:text-amber-300">
                This record belongs to the historical simulated demonstration incident catalog (INC-8492). It was generated from static test templates and is <strong>not</strong> an evidence-grounded Gemini investigation. To view a real Gemini investigation, select a correlation group above.
              </p>
            </div>
          </div>
        )}

        {/* Error / Provider Failure Banner */}
        {error && (
          <ErrorState
            title="AI Investigation Service Notice"
            message={error.message}
            details={error.details}
            onRetry={selectedCorrelation ? () => handleTriggerInvestigation(false) : undefined}
          />
        )}

        {/* State: In-Flight Generation Indicator */}
        {generating && (
          <div className="p-space-xl rounded-xl bg-surface-container-lowest border border-primary/30 shadow-sm flex flex-col items-center justify-center text-center gap-space-sm animate-pulse">
            <span className="material-symbols-outlined text-[36px] text-primary animate-spin">
              auto_awesome
            </span>
            <h3 className="font-title-md text-title-md text-on-surface font-semibold">
              Synthesizing Evidence-Grounded Investigation...
            </h3>
            <p className="font-body-default text-body-default text-secondary max-w-lg">
              Submitting sanitized anomaly events, service topology DAG, and deterministic ranked candidates to Google Gemini Flash. Validating factual grounding against telemetry records.
            </p>
          </div>
        )}

        {/* Section 1: Gemini Grounded Synthesis (When Available) */}
        {result && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h2 className="font-title-md text-title-md text-on-surface font-semibold">
                  Gemini Multi-Signal Synthesis &amp; Incident Summary
                </h2>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {result.conclusion_status && (
                  <span className={`px-2 py-0.5 rounded font-mono-badge text-mono-badge font-semibold uppercase ${
                    result.conclusion_status === 'INCONCLUSIVE'
                      ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                      : result.conclusion_status === 'CORRELATION_ONLY'
                      ? 'bg-secondary-container text-on-secondary-fixed'
                      : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                  }`}>
                    {result.conclusion_status}
                  </span>
                )}
                {result.confidence_level && (
                  <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface font-mono-badge text-mono-badge font-semibold uppercase">
                    AI CONFIDENCE: {result.confidence_level}
                  </span>
                )}
                <span className="px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed-variant font-mono-badge text-mono-badge font-semibold uppercase">
                  LLM SYNTHESIS • EVIDENCE GROUNDED
                </span>
              </div>
            </div>

            {investigation?.evidence_stale && (
              <div className="p-space-sm rounded-lg bg-amber-500/10 border border-amber-500/30 flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="text-amber-900 dark:text-amber-200">
                  Underlying multi-signal evidence was recalculated after this investigation was generated. Historical snapshot preserved.
                </span>
                <Button
                  variant="surface"
                  size="sm"
                  icon="replay"
                  disabled={generating}
                  onClick={() => handleTriggerInvestigation(true)}
                >
                  Re-run on Updated Evidence
                </Button>
              </div>
            )}

            {/* Incident Summary Paragraph */}
            <div className="p-space-md rounded-lg bg-surface-container-low flex flex-col gap-space-xs border border-outline-variant/20">
              <span className="font-caption-ui text-caption-ui uppercase text-secondary font-semibold font-mono-badge">
                Executive Incident Summary
              </span>
              <p className="font-body-default text-body-default text-on-surface leading-relaxed">
                {result.incident_summary}
              </p>
              {result.confidence_explanation && (
                <p className="text-xs text-secondary italic pt-1 border-t border-outline-variant/15">
                  Confidence rationale: {result.confidence_explanation}
                </p>
              )}
            </div>

            {/* Root Cause Explanation Card */}
            <div className="p-space-md rounded-lg bg-surface-container-lowest border border-primary/20 flex flex-col gap-space-sm">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="material-symbols-outlined text-primary text-[20px]">psychology</span>
                  <span className="font-title-sm font-semibold text-on-surface">
                    {result.conclusion_status === 'INCONCLUSIVE' ? 'Primary Hypothesis (Unconfirmed)' : 'Identified Initiating Service'}: {result.root_cause_analysis.service_name}
                  </span>
                  {result.suspected_operation && (
                    <span className="px-2 py-0.5 rounded bg-surface-container text-primary font-mono-caption text-[11px] font-semibold">
                      Op: {result.suspected_operation}
                    </span>
                  )}
                </div>
                <span className="px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed font-mono-badge text-[11px] font-semibold">
                  {result.conclusion_status === 'INCONCLUSIVE' ? 'INCONCLUSIVE' : 'AI HYPOTHESIS'}
                </span>
              </div>
              <p className="font-body-default text-body-default text-on-surface-variant leading-relaxed">
                {result.root_cause_analysis.explanation}
              </p>

              {result.root_cause_analysis.contributing_factors && result.root_cause_analysis.contributing_factors.length > 0 && (
                <div className="flex flex-col gap-1.5 pt-2 border-t border-outline-variant/20">
                  <span className="text-xs font-semibold text-on-surface font-mono-badge uppercase">
                    Contributing Factors:
                  </span>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {result.root_cause_analysis.contributing_factors.map((factor, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs text-secondary bg-surface-container-low p-2 rounded">
                        <span className="material-symbols-outlined text-[15px] text-primary shrink-0 mt-0.5">
                          arrow_right
                        </span>
                        <span>{factor}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {((result.alternative_explanations?.length || 0) > 0 || (result.contradictory_evidence?.length || 0) > 0) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-2 border-t border-outline-variant/20 text-xs">
                  {(result.contradictory_evidence?.length || 0) > 0 && (
                    <div className="p-2 rounded bg-error-container/25 border border-error/20 text-on-error-container">
                      <div className="font-semibold font-mono-badge uppercase text-[10px] mb-1">Contradictory Evidence</div>
                      {result.contradictory_evidence?.map((ce, idx) => (
                        <div key={idx}>• {ce}</div>
                      ))}
                    </div>
                  )}
                  {(result.alternative_explanations?.length || 0) > 0 && (
                    <div className="p-2 rounded bg-surface-container-low border border-outline-variant/20 text-secondary">
                      <div className="font-semibold font-mono-badge uppercase text-[10px] mb-1">Plausible Alternatives</div>
                      {result.alternative_explanations?.map((alt, idx) => (
                        <div key={idx}>• {alt}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* State: In-Progress Status Card (When background/in-flight investigation exists) */}
        {!generating && !result && !isLegacyDemo && selectedCorrelation && (investigation?.status === 'RUNNING' || investigation?.status === 'PENDING') && (
          <div className="p-space-xl rounded-xl bg-surface-container-lowest border border-primary/30 shadow-sm flex flex-col items-center justify-center text-center gap-space-sm">
            <div className="w-12 h-12 rounded-xl bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200 flex items-center justify-center mb-1">
              <span className="material-symbols-outlined text-[28px] animate-spin">hourglass_top</span>
            </div>
            <h3 className="font-title-md text-title-md text-on-surface font-semibold">
              Investigation In Progress ({investigation.status})
            </h3>
            <p className="font-body-default text-body-default text-secondary max-w-md">
              An evidence-grounded investigation is currently being synthesized for this correlation group. Click Refresh to check for completion.
            </p>
            <Button
              variant="surface"
              icon="refresh"
              className="mt-2"
              onClick={() => loadData(selectedCorrelation.id)}
            >
              Refresh Status
            </Button>
          </div>
        )}

        {/* State: No Investigation Generated Yet (Prompt user to generate) */}
        {!generating && !result && !isLegacyDemo && selectedCorrelation && !investigation && (
          <div className="p-space-xl rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm flex flex-col items-center justify-center text-center gap-space-sm">
            <div className="w-12 h-12 rounded-xl bg-primary-fixed/30 text-primary flex items-center justify-center mb-1">
              <span className="material-symbols-outlined text-[28px]">auto_awesome</span>
            </div>
            <h3 className="font-title-md text-title-md text-on-surface font-semibold">
              No Gemini AI Investigation Generated Yet
            </h3>
            <p className="font-body-default text-body-default text-secondary max-w-md">
              Anomaly correlation and deterministic 4-factor ranking are complete below. Click below to synthesize an evidence-grounded incident report and recovery plan with Google Gemini Flash.
            </p>
            <Button
              variant="primary"
              icon="auto_awesome"
              className="mt-2"
              onClick={() => handleTriggerInvestigation(false)}
            >
              Generate Gemini Investigation
            </Button>
          </div>
        )}

        {/* Section 2: Deterministic Probable Root-Cause Ranking (Pre-LLM Algorithmic Baseline) */}
        {selectedCorrelation && selectedCorrelation.ranked_candidates.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Deterministic Multi-Signal Root-Cause Ranking
                </h3>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-secondary font-mono-badge uppercase">
                  ALGORITHMIC GROUND TRUTH (PRE-LLM BASELINE)
                </span>
                <Button
                  variant="surface"
                  size="sm"
                  icon={recalculating ? 'hourglass_top' : 'calculate'}
                  disabled={recalculating || selectedCorrelation.status === 'RESOLVED'}
                  onClick={handleRecalculateRca}
                >
                  {selectedCorrelation.status === 'RESOLVED'
                    ? 'Resolved Snapshot Locked'
                    : recalculating
                    ? 'Recalculating...'
                    : 'Recalculate Multi-Signal RCA'}
                </Button>
              </div>
            </div>

            <p className="text-xs text-secondary italic">
              Candidates are deterministically normalized across temporal precedence, dependency topology, blast radius, anomaly severity, persisted metric deviation, deduplicated error logs, and exclusive self-time trace bottlenecks. Unobserved telemetry never penalizes candidate scores.
            </p>

            <div className="flex flex-col gap-3">
              {selectedCorrelation.ranked_candidates.map((cand: RootCauseCandidate) => (
                <div
                  key={cand.service_id}
                  className={`p-space-md rounded-lg border flex flex-col gap-2.5 transition-colors ${
                    cand.is_probable_root_cause
                      ? 'bg-primary-fixed/20 border-primary/40'
                      : 'bg-surface-container-low border-outline-variant/20'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2 py-0.5 rounded font-mono-badge text-xs font-bold ${
                        cand.rank === 1 ? 'bg-primary text-on-primary' : 'bg-surface-container text-on-surface'
                      }`}>
                        #{cand.rank}
                      </span>
                      <span className="font-title-sm font-semibold text-on-surface">
                        {cand.service_name}
                      </span>
                      <span className="text-xs text-secondary font-mono-caption">
                        ({cand.service_identifier})
                      </span>
                      {cand.primary_suspected_operation && (
                        <span className="px-2 py-0.5 rounded bg-surface-container text-primary font-mono-caption text-[11px] font-semibold">
                          Op: {cand.primary_suspected_operation}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-semibold text-on-surface">
                        Composite: {(cand.score * 100).toFixed(1)}%
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[11px] font-mono-badge font-semibold uppercase ${
                        cand.confidence === 'HIGH'
                          ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                          : cand.confidence === 'MEDIUM'
                          ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                          : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
                      }`}>
                        {cand.confidence} CONFIDENCE
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[11px] font-mono-badge font-semibold uppercase ${
                        cand.is_probable_root_cause
                          ? 'bg-error-container text-on-error-container'
                          : 'bg-surface-container text-on-surface-variant'
                      }`}>
                        {cand.is_probable_root_cause ? 'PROBABLE CAUSE (UNCONFIRMED)' : 'CASCADE EFFECT'}
                      </span>
                    </div>
                  </div>

                  {/* Multi-Factor Breakdown Grid */}
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-2 pt-1 border-t border-outline-variant/20">
                    {[
                      { label: 'Temporal Precedence', dim: cand.breakdown.temporal_precedence },
                      { label: 'Topological Position', dim: cand.breakdown.topological_position },
                      { label: 'Blast Radius', dim: cand.breakdown.blast_radius },
                      { label: 'Severity & Dev', dim: cand.breakdown.severity_magnitude },
                      ...(cand.breakdown.metric_deviation ? [{ label: 'Metric Deviation', dim: cand.breakdown.metric_deviation }] : []),
                      ...(cand.breakdown.log_evidence ? [{ label: 'Log Evidence', dim: cand.breakdown.log_evidence }] : []),
                      ...(cand.breakdown.trace_bottleneck ? [{ label: 'Trace Bottleneck', dim: cand.breakdown.trace_bottleneck }] : []),
                    ].map(({ label, dim }) => (
                      <div key={label} className="p-2 rounded bg-surface-container-lowest/80 text-xs">
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-secondary font-medium">
                            {label} ({(dim.weight * 100).toFixed(0)}%)
                          </span>
                          {dim.available === false && (
                            <span className="px-1 rounded bg-surface-container text-[10px] text-outline font-mono-badge">
                              UNOBSERVED
                            </span>
                          )}
                        </div>
                        <div className="font-semibold text-on-surface font-mono-caption">
                          {dim.available === false ? 'N/A' : `${(dim.score * 100).toFixed(0)}%`}
                        </div>
                        <div className="text-[11px] text-secondary mt-0.5 leading-tight">
                          {dim.reason}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Supporting Evidence Bullets */}
                  {cand.supporting_evidence.length > 0 && (
                    <div className="flex flex-col gap-1 text-xs text-secondary pt-1">
                      {cand.supporting_evidence.map((evText, i) => (
                        <div key={i} className="flex items-start gap-1.5">
                          <span className="material-symbols-outlined text-[14px] text-primary shrink-0 mt-0.5">
                            check_circle
                          </span>
                          <span>{evText}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Contradictory & Missing Signal Notices */}
                  {cand.contradictory_evidence && cand.contradictory_evidence.length > 0 && (
                    <div className="p-2 rounded bg-error-container/30 border border-error/20 flex flex-col gap-1 text-xs text-on-error-container">
                      {cand.contradictory_evidence.map((cMsg, i) => (
                        <div key={i} className="flex items-start gap-1.5">
                          <span className="material-symbols-outlined text-[14px] text-error shrink-0 mt-0.5">warning</span>
                          <span>{cMsg}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {(cand.affected_downstream_services?.length || 0) > 0 && (
                    <div className="text-[11px] text-secondary font-mono-caption">
                      Affected downstream services: {cand.affected_downstream_services?.join(', ')}
                    </div>
                  )}

                  {/* Limitation Disclaimer */}
                  {cand.limitations.length > 0 && (
                    <div className="text-[11px] text-outline italic pt-0.5">
                      {cand.limitations.join(' ')}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Multi-Signal Telemetry Evidence Drawer */}
            {selectedCorrelation.evidence_summary && (
              <div className="mt-2 pt-4 border-t border-outline-variant/20 flex flex-col gap-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-title-sm font-semibold text-on-surface">
                    Correlated Multi-Signal Telemetry Snapshot
                  </span>
                  <div className="flex items-center gap-1.5 flex-wrap text-[11px] font-mono-badge">
                    {selectedCorrelation.evidence_summary.coverage.observed_signals.map((sig) => (
                      <span key={sig} className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200 uppercase">
                        {sig}
                      </span>
                    ))}
                    {selectedCorrelation.evidence_summary.coverage.missing_signals.map((sig) => (
                      <span key={sig} className="px-2 py-0.5 rounded bg-surface-container text-outline uppercase">
                        missing: {sig}
                      </span>
                    ))}
                  </div>
                </div>

                {selectedCorrelation.evidence_summary.trace_bottlenecks.length > 0 && (
                  <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold uppercase text-secondary font-mono-badge">
                      Trace Self-Time Bottlenecks &amp; Origin Error Spans
                    </span>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {selectedCorrelation.evidence_summary.trace_bottlenecks.slice(0, 4).map((tb) => (
                        <div key={`${tb.trace_id}-${tb.span_id}`} className="p-2.5 rounded-lg bg-surface-container-low border border-outline-variant/20 flex items-center justify-between gap-2 text-xs">
                          <div className="min-w-0">
                            <div className="font-semibold text-on-surface truncate">
                              {tb.service_name}: {tb.operation_name}
                            </div>
                            <div className="font-mono-caption text-secondary">
                              self-time {tb.self_time_ms.toFixed(1)}ms ({(tb.self_time_share * 100).toFixed(0)}%) • total {tb.duration_ms.toFixed(1)}ms
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => navigate(`/traces?trace_id=${encodeURIComponent(tb.trace_id)}`)}
                            className="text-primary font-mono-caption hover:underline shrink-0 cursor-pointer"
                          >
                            Trace
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {selectedCorrelation.evidence_summary.log_highlights.length > 0 && (
                  <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold uppercase text-secondary font-mono-badge">
                      Correlated Log Highlights
                    </span>
                    <div className="flex flex-col gap-1.5">
                      {selectedCorrelation.evidence_summary.log_highlights.slice(0, 4).map((lg) => (
                        <div key={lg.log_id} className="p-2 rounded bg-surface-container-low border border-outline-variant/20 flex items-center justify-between gap-2 text-xs">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={`px-1.5 py-0.5 rounded font-mono-badge text-[10px] font-semibold ${lg.level === 'ERROR' || lg.level === 'CRITICAL' ? 'bg-error-container text-on-error-container' : 'bg-surface-container text-secondary'}`}>
                              {lg.level}
                            </span>
                            <span className="font-semibold shrink-0">{lg.service_name}</span>
                            <span className="text-secondary truncate">{lg.message}</span>
                          </div>
                          {lg.trace_id && (
                            <button
                              type="button"
                              onClick={() => navigate(`/logs?trace_id=${encodeURIComponent(lg.trace_id || '')}`)}
                              className="text-primary font-mono-caption hover:underline shrink-0 cursor-pointer"
                            >
                              Logs
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Section 3: Grounded Incident Timeline */}
        {result?.timeline && result.timeline.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Evidence-Grounded Incident Timeline
                </h3>
              </div>
              <span className="text-xs text-secondary font-mono-badge uppercase">
                {result.timeline.length} VERIFIED ANOMALY OBSERVATIONS
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-outline-variant/30 text-secondary font-medium">
                    <th className="py-2 px-3">Time (UTC)</th>
                    <th className="py-2 px-3">Service</th>
                    <th className="py-2 px-3">Metric</th>
                    <th className="py-2 px-3">Severity</th>
                    <th className="py-2 px-3">Observation</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/10 font-mono-caption">
                  {result.timeline.map((ev, idx) => (
                    <tr key={idx} className="hover:bg-surface-container-low/50">
                      <td className="py-2 px-3 text-secondary whitespace-nowrap">
                        {new Date(ev.timestamp).toLocaleTimeString()}
                      </td>
                      <td className="py-2 px-3 font-semibold text-on-surface font-sans">
                        {ev.service_name}
                      </td>
                      <td className="py-2 px-3 text-secondary uppercase font-mono-caption">
                        {ev.metric_name}
                      </td>
                      <td className="py-2 px-3">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                          ev.severity.toLowerCase() === 'critical'
                            ? 'bg-error-container text-on-error-container'
                            : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                        }`}>
                          {ev.severity}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-on-surface font-sans">
                        {ev.observation}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Section 4: Source Evidence Citations & Telemetry References */}
        {result?.evidence_references && result.evidence_references.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Source Evidence Citations & Database References
                </h3>
              </div>
              <span className="text-xs text-secondary font-mono-badge uppercase">
                {result.evidence_references.length} FACTUAL CITATIONS
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {result.evidence_references.map((ref, i) => (
                <div key={i} className="p-space-md rounded-lg bg-surface-container-low border border-outline-variant/20 flex flex-col gap-1.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-mono-badge font-semibold text-primary uppercase">
                      {ref.source_record_type}
                    </span>
                    <span className="text-secondary font-mono-caption">
                      {ref.source_id.slice(0, 8)}...
                    </span>
                  </div>
                  <div className="text-secondary">
                    Cited Field: <code className="bg-surface-container px-1 rounded text-on-surface">{ref.supported_field}</code>
                  </div>
                  <p className="text-on-surface mt-1 leading-snug">
                    {ref.summary_citation}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Section 5: Declared Uncertainties & Telemetry Gaps */}
        {result?.uncertainties_and_gaps && result.uncertainties_and_gaps.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Declared Uncertainties & Telemetry Gaps
                </h3>
              </div>
              <span className="text-xs text-secondary font-mono-badge uppercase">
                TRANSPARENCY & OBSERVABILITY LIMITATIONS
              </span>
            </div>

            <div className="flex flex-col gap-2">
              {result.uncertainties_and_gaps.map((gap, i) => (
                <div key={i} className="p-space-md rounded-lg bg-amber-500/10 border border-amber-500/20 flex flex-col gap-1 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-mono-badge font-semibold text-amber-900 dark:text-amber-200 uppercase">
                      Category: {gap.category}
                    </span>
                  </div>
                  <p className="text-on-surface font-medium">
                    {gap.description}
                  </p>
                  <p className="text-secondary italic">
                    Impact on confidence: {gap.impact_on_confidence}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Section 6: Prioritized Next Diagnostic Steps */}
        {result?.prioritized_investigation_steps && result.prioritized_investigation_steps.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Prioritized Next Diagnostic Steps for SRE
                </h3>
              </div>
              <span className="text-xs text-secondary font-mono-badge uppercase">
                DIAGNOSTIC WORKFLOW
              </span>
            </div>

            <div className="flex flex-col gap-2">
              {result.prioritized_investigation_steps.map((step) => (
                <div key={step.step_number} className="p-space-md rounded-lg bg-surface-container-low border border-outline-variant/20 flex items-start gap-space-md">
                  <div className="w-7 h-7 rounded-full bg-primary text-on-primary flex items-center justify-center font-bold text-xs shrink-0">
                    {step.step_number}
                  </div>
                  <div className="flex flex-col gap-1 text-xs flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-on-surface font-sans text-sm">
                        {step.action}
                      </span>
                      <span className="px-1.5 py-0.2 rounded bg-surface-container text-secondary font-mono-caption">
                        {step.target_service}
                      </span>
                    </div>
                    <p className="text-secondary">
                      Purpose: {step.purpose}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Section 7: Recovery Recommendations (Human Approval Mandatory) */}
        {result?.remediation_recommendations && result.remediation_recommendations.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Remediation & Recovery Recommendations
                </h3>
              </div>
              <span className="px-2 py-0.5 rounded bg-error-container text-on-error-container font-mono-badge text-mono-badge font-semibold uppercase">
                HUMAN SRE APPROVAL MANDATORY
              </span>
            </div>

            <div className="flex flex-col gap-3">
              {result.remediation_recommendations.map((rec, i) => (
                <div key={i} className="p-space-md rounded-lg bg-surface-container-low border border-outline-variant/30 flex flex-col gap-2 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-title-sm font-semibold text-on-surface">
                        {rec.title}
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-surface-container text-secondary font-mono-badge uppercase">
                        Action: {rec.action_type}
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-surface-container text-secondary font-mono-badge">
                        Target: {rec.target_service}
                      </span>
                    </div>
                    <span className={`px-2 py-0.5 rounded font-mono-badge font-semibold uppercase ${
                      rec.risk_level === 'HIGH'
                        ? 'bg-error-container text-on-error-container'
                        : rec.risk_level === 'MEDIUM'
                        ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                        : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                    }`}>
                      {rec.risk_level} RISK
                    </span>
                  </div>

                  <p className="text-on-surface-variant font-medium">
                    {rec.description}
                  </p>

                  {rec.preconditions.length > 0 && (
                    <div className="flex flex-col gap-1 pt-1">
                      <span className="font-semibold text-secondary uppercase text-[10px] font-mono-badge">
                        Preconditions:
                      </span>
                      {rec.preconditions.map((p, idx) => (
                        <div key={idx} className="flex items-center gap-1.5 text-secondary">
                          <span className="material-symbols-outlined text-[13px] text-primary">check</span>
                          <span>{p}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="pt-1 text-secondary">
                    <span className="font-semibold font-mono-badge uppercase text-[10px]">Rollback Procedure: </span>
                    <span>{rec.rollback_procedure}</span>
                  </div>

                  {rec.expected_result && (
                    <div className="text-secondary">
                      <span className="font-semibold font-mono-badge uppercase text-[10px]">Expected Outcome: </span>
                      <span>{rec.expected_result}</span>
                    </div>
                  )}

                  {rec.verification_steps && rec.verification_steps.length > 0 && (
                    <div className="text-secondary">
                      <span className="font-semibold font-mono-badge uppercase text-[10px]">Verification: </span>
                      <span>{rec.verification_steps.join(' • ')}</span>
                    </div>
                  )}

                  <div className="mt-2 pt-2 border-t border-outline-variant/20 flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-secondary">
                      <span className="material-symbols-outlined text-[16px] text-primary">lock</span>
                      <span className="font-mono-badge text-[11px] font-semibold">
                        Requires SRE Sign-off (Autonomous execution prohibited)
                      </span>
                    </div>
                    <Button 
                      variant="primary" 
                      size="sm" 
                      icon="verified_user"
                      onClick={() => alert(`Remediation action '${rec.title}' acknowledged for manual execution by SRE.`)}
                    >
                      Authorize Action
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Section 8: Correlated Anomaly Telemetry Cascade Table */}
        {selectedCorrelation && selectedCorrelation.participating_events.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Correlated Anomaly Telemetry Cascade
                </h3>
              </div>
              <span className="text-xs text-secondary font-mono-badge">
                WINDOW: {new Date(selectedCorrelation.time_window_start).toLocaleTimeString()} – {new Date(selectedCorrelation.time_window_end).toLocaleTimeString()}
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-outline-variant/30 text-secondary font-medium">
                    <th className="py-2 px-3">Time (UTC)</th>
                    <th className="py-2 px-3">Service</th>
                    <th className="py-2 px-3">Metric</th>
                    <th className="py-2 px-3">Observed vs Baseline</th>
                    <th className="py-2 px-3">Severity</th>
                    <th className="py-2 px-3">Causal Link & Explanation</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/10 font-mono-caption">
                  {selectedCorrelation.participating_events.map((ev) => (
                    <tr key={ev.event_id} className="hover:bg-surface-container-low/50">
                      <td className="py-2 px-3 text-secondary whitespace-nowrap">
                        {new Date(ev.occurred_at).toLocaleTimeString()}
                      </td>
                      <td className="py-2 px-3 font-semibold text-on-surface font-sans">
                        {ev.service_name}
                      </td>
                      <td className="py-2 px-3 text-secondary uppercase">
                        {ev.metric_name}
                      </td>
                      <td className="py-2 px-3 text-on-surface">
                        <span className="font-semibold">{ev.observed_value.toFixed(1)}</span>
                        {ev.expected_baseline !== null && ev.expected_baseline !== undefined && (
                          <span className="text-secondary ml-1">
                            (base: {ev.expected_baseline.toFixed(1)}
                            {ev.deviation_pct !== null && ev.deviation_pct !== undefined ? `, +${ev.deviation_pct.toFixed(0)}%` : ''})
                          </span>
                        )}
                      </td>
                      <td className="py-2 px-3">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                          ev.severity === 'critical'
                            ? 'bg-error-container text-on-error-container'
                            : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                        }`}>
                          {ev.severity}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-on-surface font-sans">
                        {ev.correlation_reason}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Section 9: Investigation Provenance & Audit Metadata Strip */}
        {investigation && (
          <div className="p-space-md rounded-xl bg-surface-container-low/60 border border-outline-variant/20 flex flex-wrap items-center justify-between gap-space-md text-xs font-mono-caption text-secondary">
            <div className="flex items-center gap-space-md flex-wrap">
              <span>Provider: <strong className="text-on-surface">{investigation.provider}</strong></span>
              <span>Model: <strong className="text-on-surface">{investigation.model_name}</strong></span>
              <span>Prompt: <strong className="text-on-surface">{investigation.prompt_version}</strong></span>
              <span>Schema: <strong className="text-on-surface">{investigation.schema_version}</strong></span>
              {investigation.total_tokens ? (
                <span>Tokens: <strong className="text-on-surface">{investigation.total_tokens}</strong> ({investigation.prompt_tokens} in / {investigation.completion_tokens} out)</span>
              ) : null}
              {investigation.latency_ms ? (
                <span>Synthesis Latency: <strong className="text-on-surface">{investigation.latency_ms}ms</strong></span>
              ) : null}
            </div>
            {investigation.evidence_hash && (
              <div className="truncate max-w-xs text-outline">
                Hash: {investigation.evidence_hash.slice(0, 24)}...
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
