import React from 'react';
import { StatusDot } from './StatusDot';
import { HealthStatus } from '../../types';

export interface StatusPillProps {
  label: string;
  count?: number;
  active?: boolean;
  status?: HealthStatus | 'critical';
  onClick?: () => void;
  className?: string;
}

export const StatusPill: React.FC<StatusPillProps> = ({
  label,
  count,
  active = false,
  status,
  onClick,
  className = '',
}) => {
  const baseClasses = 'flex items-center gap-1.5 px-2.5 py-1 rounded-full font-caption-ui text-caption-ui transition-colors select-none cursor-pointer';

  let stateClasses = 'bg-surface-container-low hover:bg-surface-container text-on-surface';
  if (active) {
    stateClasses = 'bg-primary text-on-primary font-semibold shadow-sm';
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={`${baseClasses} ${stateClasses} ${className}`}
    >
      {status && <StatusDot status={status} size="sm" />}
      <span>{label}</span>
      {count !== undefined && (
        <span
          className={`font-mono-badge text-mono-badge px-1 rounded-full ${
            active ? 'bg-on-primary/20 text-on-primary' : 'bg-surface-container text-secondary'
          }`}
        >
          {count}
        </span>
      )}
    </button>
  );
};

