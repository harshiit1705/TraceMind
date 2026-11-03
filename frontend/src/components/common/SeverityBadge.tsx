import React from 'react';
import { SeverityLevel } from '../../types';

export interface SeverityBadgeProps {
  severity: SeverityLevel | 'SEV-0' | 'SEV-1' | 'SEV-2' | 'SEV-3';
  animated?: boolean;
  className?: string;
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({
  severity,
  animated = false,
  className = '',
}) => {
  const norm = severity.toUpperCase();
  const isCritical = norm === 'CRITICAL' || norm === 'SEV-0';
  const isHigh = norm === 'HIGH' || norm === 'SEV-1';
  const isMedium = norm === 'MEDIUM' || norm === 'SEV-2';

  let colorClasses = 'bg-surface-container text-on-surface-variant';
  if (isCritical) {
    colorClasses = 'bg-error-container text-on-error-container';
  } else if (isHigh) {
    colorClasses = 'bg-secondary-container text-on-secondary-fixed';
  } else if (isMedium) {
    colorClasses = 'bg-surface-container-high text-on-surface-variant';
  }

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded font-mono-badge text-mono-badge font-semibold select-none ${colorClasses} ${className}`}>
      {isCritical && (
        <span className="relative flex h-2 w-2">
          {animated && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-error opacity-75" />}
          <span className="relative inline-flex rounded-full h-2 w-2 bg-error" />
        </span>
      )}
      {norm}
    </span>
  );
};

