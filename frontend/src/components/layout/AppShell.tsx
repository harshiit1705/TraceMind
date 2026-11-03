import React from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopNavigation } from './TopNavigation';

export const AppShell: React.FC = () => {
  return (
    <div className="min-h-screen bg-background font-body-default text-body-default text-on-surface antialiased selection:bg-primary-fixed selection:text-on-primary-fixed">
      {/* Fixed Sidebar */}
      <Sidebar />

      {/* Main Container Area */}
      <div className="pl-60">
        {/* Fixed Top Navigation Bar */}
        <TopNavigation />

        {/* Dynamic Route Content Canvas */}
        <main className="relative pt-14 bg-background min-h-screen">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

