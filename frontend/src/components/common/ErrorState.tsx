import React from 'react';
import { Button } from './Button';

export interface ErrorStateProps {
  title?: string;
  message: string;
  code?: string;
  details?: Record<string, unknown>;
  onRetry?: () => void;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Telemetry Ingestion Error',
  message,
  code = 'API_ERROR',
  details,
  onRetry,
  className = '',
}) => {
  return (
    <div className={`p-space-lg rounded-xl bg-error-container/30 border border-error/20 flex flex-col gap-space-sm ${className}`}>
      <div className="flex items-start gap-space-sm">
        <div className="w-9 h-9 rounded-lg bg-error text-on-error flex items-center justify-center shrink-0 shadow-sm mt-0.5">
          <span className="material-symbols-outlined text-[20px]">warning</span>
        </div>
        <div className="flex flex-col flex-1">
          <div className="flex items-center gap-space-xs">
            <span className="font-title-md text-title-md text-on-surface font-semibold">
              {title}
            </span>
            <span className="font-mono-badge text-mono-badge px-1.5 py-0.5 rounded bg-error text-on-error font-medium uppercase">
              {code}
            </span>
          </div>
          <p className="font-body-default text-body-default text-error font-medium mt-1">
            {message}
          </p>
          {Boolean(details?.hint) && (
            <p className="font-mono-caption text-mono-caption text-on-surface-variant mt-1">
              {String(details?.hint)}
            </p>
          )}
        </div>
        {onRetry && (
          <Button variant="danger" size="sm" icon="replay" onClick={onRetry}>
            Retry Request
          </Button>
        )}
      </div>
      {Boolean(details?.endpoint) && (
        <div className="mt-1 pt-space-xs border-t border-error/15 font-mono-caption text-mono-caption text-secondary">
          Target Endpoint: <code className="bg-surface-container px-1 py-0.5 rounded text-on-surface">{String(details?.endpoint)}</code>
        </div>
      )}
    </div>
  );
};

