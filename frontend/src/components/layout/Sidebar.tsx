import React from 'react';
import { NavLink } from 'react-router-dom';

interface NavItem {
  path: string;
  label: string;
  icon: string;
  badge?: React.ReactNode;
}

export const Sidebar: React.FC = () => {
  const navItems: NavItem[] = [
    {
      path: '/overview',
      label: 'Overview',
      icon: 'grid_view',
    },
    {
      path: '/services',
      label: 'Services',
      icon: 'dns',
      badge: (
        <span className="font-mono-badge text-mono-badge px-1.5 py-0.2 bg-surface-container text-secondary rounded">
          42
        </span>
      ),
    },
    {
      path: '/dependency-map',
      label: 'Dependency Map',
      icon: 'hub',
    },
    {
      path: '/incidents',
      label: 'Incidents',
      icon: 'crisis_alert',
      badge: (
        <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded-full bg-error text-on-error font-medium">
          3
        </span>
      ),
    },
    {
      path: '/ai-investigations',
      label: 'AI Investigations',
      icon: 'auto_awesome',
      badge: (
        <span className="font-mono-badge text-mono-badge px-1.5 py-0.2 bg-primary-fixed text-on-primary-fixed-variant rounded font-medium">
          beta
        </span>
      ),
    },
    {
      path: '/traces',
      label: 'Traces',
      icon: 'insights',
    },
    {
      path: '/logs',
      label: 'Logs',
      icon: 'terminal',
    },
    {
      path: '/reports',
      label: 'Reports & Postmortems',
      icon: 'assignment_turned_in',
    },
    {
      path: '/settings',
      label: 'Settings',
      icon: 'settings',
    },
  ];

  return (
    <aside className="fixed left-0 top-0 h-full w-60 bg-surface-container-lowest border-r border-outline-variant/30 z-50 flex flex-col justify-between select-none">
      <div className="flex flex-col">
        {/* Brand Header */}
        <div className="h-14 px-space-md border-b border-outline-variant/20 flex items-center justify-between">
          <div className="flex items-center gap-space-sm">
            <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center text-on-primary shadow-sm shrink-0">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 12h3l3 7 4-14 3 7h5" />
              </svg>
            </div>
            <span className="font-title-md text-title-md tracking-tight text-on-surface font-semibold">
              TraceMind
            </span>
          </div>
          <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-medium uppercase tracking-wider">
            PROD
          </span>
        </div>

        {/* Navigation Stream */}
        <div className="px-space-md py-space-sm">
          <span className="font-caption-ui text-caption-ui text-outline uppercase tracking-wider font-semibold block px-space-xs mb-space-xxs">
            Telemetry &amp; Ops
          </span>
          <nav className="flex flex-col gap-0.5">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `group flex items-center justify-between px-space-sm py-2 rounded-lg transition-colors ${
                    isActive
                      ? 'bg-surface-container-high text-primary font-semibold shadow-[inset_3px_0_0_0_#3525cd]'
                      : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <div className="flex items-center gap-space-sm">
                      <span
                        className={`material-symbols-outlined text-[18px] transition-colors ${
                          isActive
                            ? 'text-primary'
                            : item.path === '/incidents'
                            ? 'text-error'
                            : item.path === '/ai-investigations'
                            ? 'text-primary'
                            : 'text-secondary group-hover:text-on-surface'
                        }`}
                      >
                        {item.icon}
                      </span>
                      <span className="font-body-medium text-body-medium">
                        {item.label}
                      </span>
                    </div>
                    {item.badge}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>

      {/* Footer Profile & Org Card */}
      <div className="p-space-sm border-t border-outline-variant/20 flex flex-col gap-space-xs bg-surface-container-lowest">
        <div className="p-space-xs rounded-lg hover:bg-surface-container-low transition-colors cursor-pointer flex items-center justify-between">
          <div className="flex items-center gap-space-xs overflow-hidden">
            <span className="material-symbols-outlined text-[18px] text-secondary flex-shrink-0">
              corporate_fare
            </span>
            <div className="flex flex-col truncate">
              <span className="font-caption-ui text-caption-ui text-on-surface font-semibold truncate">
                Acme Cloud Infra
              </span>
              <span className="font-mono-caption text-mono-caption text-outline truncate">
                org-prod-us-east-1
              </span>
            </div>
          </div>
          <span className="material-symbols-outlined text-[16px] text-outline">
            unfold_more
          </span>
        </div>

        <div className="pt-space-xs border-t border-outline-variant/10 flex items-center justify-between px-space-xs">
          <div className="flex items-center gap-space-xs">
            <div className="relative">
              <img
                alt="Profile"
                className="w-8 h-8 rounded-full object-cover"
                src="https://lh3.googleusercontent.com/aida-public/AB6AXuDo3kLijSZYHG5cklsGlhEVl_33IIW292avLA7wa-RCbLUCsSUFxVQF2ftjV4jKanAPJKsZ6sdledYPP9tsB59Q8De1l3X82IBf9uph5-xhfaeyTxRMsD6-rBBq_W3nLyf94cjxvvPvNDc8nGHpihNP30MceWPvzNJhk6tknmn2DkFiBYkcQ241_pSVrkMi89gwgKFkK1hOe_g9xida9GS2X2pnK6k29JwiDBggBoI"
              />
              <span className="absolute bottom-0 right-0 w-2 h-2 rounded-full bg-primary ring-2 ring-surface-container-lowest" />
            </div>
            <div className="flex flex-col">
              <span className="font-caption-ui text-caption-ui text-on-surface font-semibold leading-tight">
                Alex Chen
              </span>
              <span className="font-mono-caption text-mono-caption text-outline leading-tight">
                Staff SRE
              </span>
            </div>
          </div>
          <NavLink
            to="/settings"
            className="text-outline hover:text-on-surface p-1 rounded hover:bg-surface-container transition-colors"
            title="Settings"
          >
            <span className="material-symbols-outlined text-[18px]">
              keyboard_command_key
            </span>
          </NavLink>
        </div>
      </div>
    </aside>
  );
};

