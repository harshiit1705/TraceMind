import React, { useEffect, useState } from 'react';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, LoadingSpinner } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { AiInvestigationSummary, CorrelationGroup, RootCauseCandidate } from '../../types';

export const AiInvestigationPage: React.FC = () => {
  const [investigation, setInvestigation] = useState<AiInvestigationSummary | null>(null);
  const [correlation, setCorrelation] = useState<CorrelationGroup | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    Promise.all([
      apiClient.getInvestigation(),
      apiClient.getCorrelations().then((res) => (res.data.length > 0 ? res.data[0] : null)),
    ])
      .then(([invRes, corrRes]) => {
        if (mounted) {
          setInvestigation(invRes.data);
          setCorrelation(corrRes);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  if (loading) {
    return <LoadingSpinner message="Correlating distributed telemetry and ranking causal evidence..." />;
  }

  return (
    <div className="w-full px-margin-desktop py-margin-desktop">
      <div className="flex flex-col w-full gap-space-lg">
        {/* Header */}
        <PageHeader
          category="AI Investigation Center"
          categoryBadge={
            <div className="flex items-center gap-1.5">
              <span className="text-primary font-medium">{investigation?.id || 'INV-2024-8492'}</span>
              <span className="px-1.5 py-0.5 rounded bg-primary-fixed text-on-primary-fixed-variant font-mono-badge text-mono-badge uppercase tracking-wider font-semibold">
                Autonomous Agent #4
              </span>
            </div>
          }
          title={investigation?.rootCauseTitle || 'Root Cause Investigation: INC-8492 (Aurora DB Pool Saturation)'}
          subtitle={`Telemetry Confidence: ${correlation ? Math.round(correlation.confidence_score * 100) : (investigation?.confidenceScore || 94)}% • ${correlation?.events_count || 3} cross-service anomalies correlated • Topology ${correlation?.topology_complete ? 'Verified DAG' : 'Unmapped'}`}
          actions={
            <>
              <Button variant="surface" icon="ios_share">Export Report</Button>
              <Button variant="surface" icon="replay">Re-run Analysis</Button>
              <Button variant="primary" icon="bolt">Apply Remediation</Button>
            </>
          }
        />

        {/* Primary Finding Card */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-space-xs">
              <span className="w-1.5 h-4 rounded-full bg-primary" />
              <h2 className="font-title-md text-title-md text-on-surface font-semibold">
                Primary Finding: Probable Root Cause
              </h2>
            </div>
            <span className="px-2 py-0.5 rounded bg-error-container text-on-error-container font-mono-badge text-mono-badge font-semibold">
              CRITICAL CASCADE PATHWAY
            </span>
          </div>

          <div className="p-space-md rounded-lg bg-surface-container-low flex flex-col md:flex-row items-start gap-space-md">
            <div className="w-9 h-9 rounded-lg bg-error text-on-error flex items-center justify-center shrink-0 shadow-sm mt-0.5">
              <span className="material-symbols-outlined text-[20px]">warning</span>
            </div>
            <div className="flex flex-col gap-space-xs">
              <div className="font-body-medium text-body-medium text-on-surface font-semibold">
                Database connection pool exhaustion caused query wait timeouts on <code className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface font-mono-caption text-mono-caption">aurora-prod-cluster-02</code>, cascading to Payment Service (HTTP 504) and Order Service (HTTP 502).
              </div>
              <p className="font-body-default text-body-default text-secondary">
                {correlation?.summary || investigation?.rootCauseDescription || 'Continuous transactions held row-level exclusive locks against partition orders_ledger_2024_q2.'}
              </p>
            </div>
          </div>
        </div>

        {/* Ranked Probable Root Causes */}
        {correlation && correlation.ranked_candidates.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Ranked Probable Root-Cause Candidates
                </h3>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-secondary font-mono-badge">
                  DETERMINISTIC MULTI-FACTOR RANKING
                </span>
              </div>
            </div>

            <div className="flex flex-col gap-3">
              {correlation.ranked_candidates.map((cand: RootCauseCandidate) => (
                <div
                  key={cand.service_id}
                  className={`p-space-md rounded-lg border flex flex-col gap-2.5 transition-colors ${
                    cand.is_probable_root_cause
                      ? 'bg-primary-fixed/20 border-primary/40'
                      : 'bg-surface-container-low border-outline-variant/20'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
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
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-on-surface">
                        Score: {(cand.score * 100).toFixed(1)}%
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

                  {/* 4-Factor Breakdown Grid */}
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-2 pt-1 border-t border-outline-variant/20">
                    <div className="p-2 rounded bg-surface-container-lowest/80 text-xs">
                      <div className="text-secondary font-medium">Temporal Precedence (35%)</div>
                      <div className="font-semibold text-on-surface font-mono-caption">
                        {(cand.breakdown.temporal_precedence.score * 100).toFixed(0)}%
                      </div>
                      <div className="text-[11px] text-secondary mt-0.5 leading-tight">
                        {cand.breakdown.temporal_precedence.reason}
                      </div>
                    </div>

                    <div className="p-2 rounded bg-surface-container-lowest/80 text-xs">
                      <div className="text-secondary font-medium">Topological Position (35%)</div>
                      <div className="font-semibold text-on-surface font-mono-caption">
                        {(cand.breakdown.topological_position.score * 100).toFixed(0)}%
                      </div>
                      <div className="text-[11px] text-secondary mt-0.5 leading-tight">
                        {cand.breakdown.topological_position.reason}
                      </div>
                    </div>

                    <div className="p-2 rounded bg-surface-container-lowest/80 text-xs">
                      <div className="text-secondary font-medium">Blast Radius (15%)</div>
                      <div className="font-semibold text-on-surface font-mono-caption">
                        {(cand.breakdown.blast_radius.score * 100).toFixed(0)}%
                      </div>
                      <div className="text-[11px] text-secondary mt-0.5 leading-tight">
                        {cand.breakdown.blast_radius.reason}
                      </div>
                    </div>

                    <div className="p-2 rounded bg-surface-container-lowest/80 text-xs">
                      <div className="text-secondary font-medium">Severity & Dev (15%)</div>
                      <div className="font-semibold text-on-surface font-mono-caption">
                        {(cand.breakdown.severity_magnitude.score * 100).toFixed(0)}%
                      </div>
                      <div className="text-[11px] text-secondary mt-0.5 leading-tight">
                        {cand.breakdown.severity_magnitude.reason}
                      </div>
                    </div>
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

                  {/* Limitation Disclaimer */}
                  {cand.limitations.length > 0 && (
                    <div className="text-[11px] text-outline italic pt-0.5">
                      {cand.limitations[0]}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Correlated Anomaly Telemetry Timeline */}
        {correlation && correlation.participating_events.length > 0 && (
          <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-space-xs">
                <span className="w-1.5 h-4 rounded-full bg-primary" />
                <h3 className="font-title-md text-title-md text-on-surface font-semibold">
                  Correlated Anomaly Telemetry Cascade
                </h3>
              </div>
              <span className="text-xs text-secondary font-mono-badge">
                WINDOW: {new Date(correlation.time_window_start).toLocaleTimeString()} – {new Date(correlation.time_window_end).toLocaleTimeString()}
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
                  {correlation.participating_events.map((ev) => (
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
      </div>
    </div>
  );
};
