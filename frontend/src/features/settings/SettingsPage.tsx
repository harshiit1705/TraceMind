import React, { useEffect, useState } from 'react';
import { PageHeader } from '../../components/layout/PageHeader';
import { Button, LoadingSpinner } from '../../components/common';
import { apiClient } from '../../services/apiClient';
import { SystemSettings } from '../../types';

export const SettingsPage: React.FC = () => {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<string>('general');

  useEffect(() => {
    let mounted = true;
    apiClient.getSettings()
      .then((res) => {
        if (mounted) {
          setSettings(res.data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, []);

  if (loading) {
    return <LoadingSpinner message="Loading workspace preferences..." />;
  }

  const tabs = [
    { id: 'general', label: 'General & Workspace', icon: 'tune' },
    { id: 'alerts', label: 'Alert Rules', icon: 'notifications_active', badge: '18' },
    { id: 'channels', label: 'Notification Channels', icon: 'hub', badge: 'Slack, PagerDuty' },
    { id: 'copilot', label: 'AI Copilot & Remediation', icon: 'smart_toy', badge: 'active' },
    { id: 'team', label: 'Team & RBAC', icon: 'group' },
    { id: 'keys', label: 'API Keys', icon: 'key' },
  ];

  return (
    <div className="w-full px-margin-desktop py-margin-desktop">
      <div className="flex flex-col w-full gap-space-lg">
        {/* Header */}
        <PageHeader
          category="Organization"
          categoryBadge={<span className="text-on-surface-variant">System Preferences</span>}
          title="Settings"
          titleBadge={
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-primary-fixed text-on-primary-fixed-variant font-medium uppercase tracking-wider">
              v3.8.4-prod
            </span>
          }
          subtitle="Manage workspace preferences, observability ingestion rules, alert channels, and AI copilot policies."
          actions={
            <>
              <div className="flex items-center gap-1.5 px-space-sm py-1.5 rounded-lg bg-surface-container-low text-secondary font-mono-caption text-mono-caption">
                <span className="w-2 h-2 rounded-full bg-tertiary" />
                <span>Config sync: <strong className="text-on-surface font-medium">Synced</strong></span>
              </div>
              <Button variant="secondary" icon="history">Audit Log</Button>
            </>
          }
        />

        {/* Sub-Tabs Navigation */}
        <div className="flex items-center gap-1 overflow-x-auto py-1 scrollbar-none border-b border-outline-variant/20 pb-2">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`px-space-md py-2 rounded-lg font-body-medium text-body-medium flex items-center gap-2 whitespace-nowrap transition-colors ${
                activeTab === tab.id
                  ? 'bg-surface-container-high text-primary font-semibold shadow-sm'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-low'
              }`}
            >
              <span className="material-symbols-outlined text-[18px]">{tab.icon}</span>
              <span>{tab.label}</span>
              {tab.badge && (
                <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-surface-container text-secondary font-medium">
                  {tab.badge}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Workspace & Ingestion Configuration Panel */}
        <section className="bg-surface-container-lowest rounded-xl shadow-sm border border-outline-variant/30 p-space-lg flex flex-col gap-space-md">
          <div className="flex items-start justify-between pb-space-xs border-b border-outline-variant/20">
            <div className="flex items-center gap-space-sm">
              <div className="w-8 h-8 rounded-lg bg-surface-container-low flex items-center justify-center text-primary">
                <span className="material-symbols-outlined text-[20px]">layers</span>
              </div>
              <div>
                <h2 className="font-headline-sm text-headline-sm text-on-surface tracking-tight font-semibold">
                  Workspace &amp; Ingestion Configuration
                </h2>
                <p className="font-body-default text-body-default text-secondary">
                  Global tenant variables, OpenTelemetry ingest topology, and telemetry retention cycles.
                </p>
              </div>
            </div>
            <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-surface-container text-secondary uppercase tracking-wider font-medium">
              TENANT_ID: {settings?.tenantId || 'TM-98241'}
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md pt-space-xs">
            <div className="flex flex-col gap-1.5 p-space-md bg-surface rounded-lg">
              <span className="font-caption-ui text-caption-ui uppercase text-outline font-semibold tracking-wider">
                Workspace Name
              </span>
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                {settings?.workspaceName || 'Acme Cloud Infrastructure'}
              </span>
              <span className="font-mono-caption text-mono-caption text-secondary">
                Production cluster tenant for global checkout &amp; microservices
              </span>
            </div>

            <div className="flex flex-col gap-1.5 p-space-md bg-surface rounded-lg">
              <span className="font-caption-ui text-caption-ui uppercase text-outline font-semibold tracking-wider">
                Primary Region &amp; Cloud Provider
              </span>
              <span className="font-title-md text-title-md text-on-surface font-semibold">
                {settings?.primaryRegion || 'us-east-1 (AWS Northern Virginia)'}
              </span>
              <span className="font-mono-caption text-mono-caption text-secondary">
                Direct AWS PrivateLink peering enabled across VPC-982
              </span>
            </div>
          </div>
        </section>

        {/* Phase 2.1 Settings Scaffold Notice */}
        <div className="p-space-lg rounded-xl bg-surface-container-lowest shadow-sm border border-outline-variant/30">
          <h3 className="font-title-md text-title-md text-on-surface font-semibold mb-1">
            Administration &amp; Copilot Policy Editor Ready for Phase 2.4
          </h3>
          <p className="font-body-default text-body-default text-on-surface-variant">
            Full alert rule configuration, Slack/PagerDuty webhook testing, PII scrubbing toggles, and team member RBAC management tables are scoped for Phase 2.4.
          </p>
        </div>
      </div>
    </div>
  );
};

