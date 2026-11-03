import React from 'react';
import { Link } from 'react-router-dom';
import { Button } from '../../components/common';

export const NotFoundPage: React.FC = () => {
  return (
    <div className="w-full px-margin-desktop py-space-2xl flex flex-col items-center justify-center text-center min-h-[60vh]">
      <div className="w-16 h-16 rounded-2xl bg-surface-container flex items-center justify-center text-primary mb-space-md shadow-sm">
        <span className="material-symbols-outlined text-[36px]">travel_explore</span>
      </div>
      <span className="font-mono-badge text-mono-badge px-2 py-0.5 rounded bg-error-container text-on-error-container font-semibold uppercase mb-2">
        HTTP 404 • UNRESOLVED TELEMETRY ROUTE
      </span>
      <h1 className="font-display-lg text-display-lg text-on-surface font-semibold tracking-tight mb-2">
        Route Not Found
      </h1>
      <p className="font-body-default text-body-default text-on-surface-variant max-w-md mb-space-lg">
        The requested URL path does not map to any active TraceMind diagnostic canvas or service endpoint.
      </p>
      <Link to="/overview">
        <Button variant="primary" icon="grid_view">
          Return to Overview Dashboard
        </Button>
      </Link>
    </div>
  );
};

