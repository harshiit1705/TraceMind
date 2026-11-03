import React from 'react';
import { HealthStatus } from '../../types';

export interface StatusDotProps {
  status: HealthStatus | 'critical' | 'normal';
  pulse?: boolean;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export const StatusDot: React.FC<StatusDotProps> = ({
  status,
  pulse = false,
  size = 'md',
  className = '',
}) => {
  const sizeMap = {
    sm: 'w-1.5 h-1.5',
    md: 'w-2 h-2',
    lg: 'w-2.5 h-2.5',
  };

  const colorMap = {
    healthy: 'bg-primary-container',
    normal: 'bg-primary-container',
    degraded: 'bg-secondary',
    unhealthy: 'bg-error',
    critical: 'bg-error',
  };

  const dotSize = sizeMap[size];
  const dotColor = colorMap[status] || 'bg-outline';

  if (pulse && (status === 'critical' || status === 'unhealthy')) {
    return (
      <span className={`relative flex ${dotSize} ${className}`}>
        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${dotColor} opacity-75`} />
        <span className={`relative inline-flex rounded-full ${dotSize} ${dotColor}`} />
      </span>
    );
  }

  return <span className={`inline-block rounded-full ${dotSize} ${dotColor} ${className}`} />;
};

