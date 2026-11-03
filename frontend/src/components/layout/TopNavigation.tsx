import React from 'react';
import { apiClient } from '../../services/apiClient';

export const TopNavigation: React.FC = () => {
  const dataMode = apiClient.getDataMode();

  return (
    <header className="fixed top-0 left-60 right-0 h-14 bg-surface-container-lowest/95 backdrop-blur-md border-b border-outline-variant/25 z-40 flex items-center justify-between px-space-lg shadow-[0_1px_4px_rgba(11,28,48,0.03)] select-none">
      {/* Scope / Workspace selectors */}
      <div className="flex items-center gap-space-md">
        <div className="flex items-center gap-space-xs bg-surface-container-low px-space-sm py-1 rounded-lg border border-outline-variant/30 cursor-pointer hover:bg-surface-container transition-colors">
          <span className="material-symbols-outlined text-[16px] text-primary">folder_open</span>
          <span className="font-body-medium text-body-medium text-on-surface font-medium">
            Core E-Commerce &amp; Payments
          </span>
          <span className="material-symbols-outlined text-[16px] text-outline">expand_more</span>
        </div>

        <div className="flex items-center gap-1.5 px-space-xs py-1 rounded bg-secondary-container/40 border border-secondary-container text-on-secondary-fixed text-caption-ui font-caption-ui cursor-pointer hover:bg-secondary-container/70 transition-colors">
          <span className="w-1.5 h-1.5 rounded-full bg-primary" />
          <span>Production</span>
          <span className="material-symbols-outlined text-[14px] text-on-secondary-fixed-variant">
            arrow_drop_down
          </span>
        </div>

        <div className="h-4 w-px bg-outline-variant/30" />

        <div className="flex items-center gap-space-xs text-on-surface-variant font-mono-body text-mono-body bg-surface-container-low px-space-sm py-1 rounded-lg border border-outline-variant/30 cursor-pointer hover:bg-surface-container transition-colors">
          <span className="material-symbols-outlined text-[16px] text-secondary">schedule</span>
          <span>Last 15 minutes</span>
          <span className="inline-flex items-center gap-1 ml-1 pl-1.5 border-l border-outline-variant/30 text-on-tertiary-fixed-variant text-mono-caption font-mono-caption">
            <span className="w-1.5 h-1.5 rounded-full bg-tertiary animate-pulse" />
            30s
          </span>
        </div>
      </div>

      {/* Central Omnibar Search */}
      <div className="flex items-center gap-space-md flex-1 max-w-lg mx-space-lg">
        <div className="relative w-full">
          <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-[18px] text-outline pointer-events-none">
            search
          </span>
          <input
            type="text"
            placeholder="Search traces, span IDs, services, logs (Cmd+K)"
            className="w-full h-8 pl-9 pr-14 bg-surface text-on-surface placeholder:text-outline border border-outline-variant/40 rounded-lg text-body-default font-body-default focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all"
          />
          <kbd className="absolute right-2 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-mono-caption font-mono-caption text-outline bg-surface-container border border-outline-variant/30 rounded">
            ⌘K
          </kbd>
        </div>
      </div>

      {/* Right Controls, Alerts & User Profile */}
      <div className="flex items-center gap-space-sm">
        {/* Explicit Data Mode Tag */}
        <span
          className={`font-mono-badge text-mono-badge px-2 py-0.5 rounded border ${
            dataMode === 'api'
              ? 'bg-secondary-container text-on-secondary-fixed border-secondary-container'
              : 'bg-surface-container-high text-on-surface-variant border-outline-variant/30'
          }`}
          title={`Active Data Mode: ${dataMode.toUpperCase()}`}
        >
          MODE: {dataMode.toUpperCase()}
        </span>

        <div className="relative">
          <button
            type="button"
            className="relative p-1.5 rounded-lg text-secondary hover:text-on-surface hover:bg-surface-container transition-colors"
            title="Notifications"
          >
            <span className="material-symbols-outlined text-[20px]">notifications</span>
            <span className="absolute top-1 right-1 flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-error opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-error" />
            </span>
          </button>
        </div>

        <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-error-container text-on-error-container text-mono-caption font-mono-caption border border-error/20">
          <span className="w-1.5 h-1.5 rounded-full bg-error" />
          <span>2 critical</span>
        </div>

        <div className="h-4 w-px bg-outline-variant/30 mx-1" />

        <div className="relative cursor-pointer">
          <img
            alt="Profile"
            className="w-8 h-8 rounded-full object-cover ring-1 ring-outline-variant/40"
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuDo3kLijSZYHG5cklsGlhEVl_33IIW292avLA7wa-RCbLUCsSUFxVQF2ftjV4jKanAPJKsZ6sdledYPP9tsB59Q8De1l3X82IBf9uph5-xhfaeyTxRMsD6-rBBq_W3nLyf94cjxvvPvNDc8nGHpihNP30MceWPvzNJhk6tknmn2DkFiBYkcQ241_pSVrkMi89gwgKFkK1hOe_g9xida9GS2X2pnK6k29JwiDBggBoI"
          />
          <span className="absolute bottom-0 right-0 w-2 h-2 rounded-full bg-primary ring-2 ring-surface-container-lowest" />
        </div>
      </div>
    </header>
  );
};

