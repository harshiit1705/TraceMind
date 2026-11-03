import React, { useEffect, useState } from 'react';
import { PageHeader } from '../../components/layout/PageHeader';
import { KpiCard, Button, LoadingSpinner } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { PostmortemReport } from '../../types';

export const ReportsPage: React.FC = () => {
  const [postmortem, setPostmortem] = useState<PostmortemReport | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    apiClient.getPostmortem()
      .then((res) => {
        if (mounted) {
          setPostmortem(res.data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, []);

  if (loading) {
    return <LoadingSpinner message="Aggregating postmortem retrospectives..." />;
  }

  return (
    <div className="w-full px-margin-desktop py-margin-desktop">
      <div className="flex flex-col w-full gap-space-lg">
        {/* Header */}
        <PageHeader
          category="Engineering Reliability"
          categoryBadge={
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed font-medium">
              RELIABILITY HQ
            </span>
          }
          title="Reports &amp; Postmortems"
          subtitle="Engineering reliability analysis, system outage retrospectives, autonomous incident diagnostics, and continuous SLO trend reporting."
          actions={
            <>
              <div className="flex items-center gap-1.5 px-space-sm py-1.5 rounded-lg bg-surface-container-lowest shadow-sm text-on-surface font-mono-body text-mono-body cursor-pointer hover:bg-surface-container-low transition-colors">
                <span className="material-symbols-outlined text-[16px] text-secondary">date_range</span>
                <span>Last 30 Days</span>
                <span className="material-symbols-outlined text-[16px] text-outline">expand_more</span>
              </div>
              <Button variant="secondary" icon="download">Export (PDF/CSV)</Button>
              <Button variant="primary" icon="add_circle">Generate New Postmortem</Button>
            </>
          }
        />

        {/* 4-Card Compact Reliability Metrics Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-space-md">
          <KpiCard
            title="Total Incidents (30d)"
            value="14"
            icon="emergency"
            subtitle="events tracked"
          />
          <KpiCard
            title="Mean Time to Detect (MTTD)"
            value="1m 42s"
            icon="radar"
            iconColor="text-tertiary"
            deltaText="↓ 24s vs last mo"
            deltaType="positive"
            subtitle="Target SLA: < 2m 30s"
          />
          <KpiCard
            title="Mean Time to Resolve (MTTR)"
            value="18m 10s"
            icon="timer"
            iconColor="text-primary"
            deltaText="↓ 4m 15s imprv"
            deltaType="positive"
            subtitle="Target SLA: < 30m 00s"
          />
          <KpiCard
            title="System SLO Compliance"
            value="99.94%"
            icon="monitoring"
            iconColor="text-error"
            deltaText="-0.01% breach"
            deltaType="error"
            subtitle="Target: 99.95%"
          />
        </div>

        {/* Active Postmortem Executive Summary */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30 flex flex-col gap-space-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-space-xs">
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                {postmortem?.title || 'Postmortem: INC-8492 — Aurora DB Connection Pool Exhaustion'}
              </span>
              <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed">
                IN REVIEW (80%)
              </span>
            </div>
            <span className="font-mono-caption text-mono-caption text-outline">
              Commander: {postmortem?.commander}
            </span>
          </div>

          <p className="font-body-default text-body-default text-on-surface-variant leading-relaxed">
            {postmortem?.executiveSummary}
          </p>
        </div>

        {/* Phase 2.1 Postmortem Scaffold Notice */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30">
          <h3 className="font-title-md text-title-md text-on-surface font-semibold mb-1">
            Retrospective Studio &amp; Action Item Tracking Ready for Phase 2.4
          </h3>
          <p className="font-body-default text-body-default text-on-surface-variant">
            Full postmortem chronological sequence, business &amp; technical impact stats, root cause breakdown, and action item registry tables are scoped for Phase 2.4.
          </p>
        </div>
      </div>
    </div>
  );
};

