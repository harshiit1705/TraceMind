import React, { useEffect, useState } from 'react';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, LoadingSpinner } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { AiInvestigationSummary } from '../../types';

export const AiInvestigationPage: React.FC = () => {
  const [investigation, setInvestigation] = useState<AiInvestigationSummary | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    apiClient.getInvestigation()
      .then((res) => {
        if (mounted) {
          setInvestigation(res.data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, []);

  if (loading) {
    return <LoadingSpinner message="Correlating distributed spans and hypothesis weights..." />;
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
          subtitle={`Telemetry Confidence: ${investigation?.confidenceScore || 94}% • ${investigation?.correlationScope || 42} microservices correlated • ${investigation?.spansAnalyzed || 128400} spans analyzed`}
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
                {investigation?.rootCauseDescription || 'Continuous transactions held row-level exclusive locks against partition orders_ledger_2024_q2.'}
              </p>
            </div>
          </div>
        </div>

        {/* Phase 2.1 Scaffold Notice */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30">
          <h3 className="font-title-md text-title-md text-on-surface font-semibold mb-1">
            Autonomous Investigation Canvas Ready for Phase 2.3
          </h3>
          <p className="font-body-default text-body-default text-on-surface-variant">
            Failure propagation directed graph (4 layers), ranked hypotheses analysis cards, correlated evidence verification table, and dry-run remediation playbooks are fully specified and scoped for Phase 2.3.
          </p>
        </div>
      </div>
    </div>
  );
};

