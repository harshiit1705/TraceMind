import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from '../components/layout/AppShell';

import { OverviewPage } from '../features/overview/OverviewPage';
import { ServicesPage } from '../features/services/ServicesPage';
import { DependencyMapPage } from '../features/dependency-map/DependencyMapPage';
import { IncidentsPage } from '../features/incidents/IncidentsPage';
import { IncidentDetailsPage } from '../features/incidents/IncidentDetailsPage';
import { AiInvestigationPage } from '../features/ai-investigation/AiInvestigationPage';
import { TraceExplorerPage } from '../features/traces/TraceExplorerPage';
import { LogsExplorerPage } from '../features/logs/LogsExplorerPage';
import { ReportsPage } from '../features/reports/ReportsPage';
import { SettingsPage } from '../features/settings/SettingsPage';
import { NotFoundPage } from '../features/common/NotFoundPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <Navigate to="/overview" replace />,
      },
      {
        path: 'overview',
        element: <OverviewPage />,
      },
      {
        path: 'services',
        element: <ServicesPage />,
      },
      {
        path: 'dependency-map',
        element: <DependencyMapPage />,
      },
      {
        path: 'incidents',
        element: <IncidentsPage />,
      },
      {
        path: 'incidents/:incidentId',
        element: <IncidentDetailsPage />,
      },
      {
        path: 'ai-investigations',
        element: <AiInvestigationPage />,
      },
      {
        path: 'ai-investigations/:id',
        element: <AiInvestigationPage />,
      },
      {
        path: 'traces',
        element: <TraceExplorerPage />,
      },
      {
        path: 'traces/:traceId',
        element: <TraceExplorerPage />,
      },
      {
        path: 'logs',
        element: <LogsExplorerPage />,
      },
      {
        path: 'reports',
        element: <ReportsPage />,
      },
      {
        path: 'settings',
        element: <SettingsPage />,
      },
      {
        path: '*',
        element: <NotFoundPage />,
      },
    ],
  },
]);

