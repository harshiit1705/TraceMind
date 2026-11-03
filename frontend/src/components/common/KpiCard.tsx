import React from 'react';

export interface KpiCardProps {
  title: string;
  value: string | number;
  valueColor?: string;
  unit?: string;
  badge?: React.ReactNode;
  icon?: string;
  iconColor?: string;
  deltaText?: string;
  deltaType?: 'positive' | 'negative' | 'neutral' | 'error';
  subtitle?: string;
  progressPercent?: number;
  progressBarColor?: string;
  indicator?: React.ReactNode;
  trend?: string;
  trendDirection?: 'up' | 'down' | 'neutral';
  onClick?: () => void;
  className?: string;
}

export const KpiCard: React.FC<KpiCardProps> = ({
  title,
  value,
  valueColor = 'text-on-surface',
  unit,
  badge,
  icon,
  iconColor = 'text-secondary',
  deltaText,
  deltaType = 'neutral',
  subtitle,
  progressPercent,
  progressBarColor = 'bg-primary',
  indicator,
  trend,
  trendDirection = 'neutral',
  onClick,
  className = '',
}) => {
  const deltaColorMap = {
    positive: 'text-primary',
    negative: 'text-error',
    error: 'text-error',
    neutral: 'text-secondary',
  };

  const trendIconMap = {
    up: 'trending_up',
    down: 'trending_down',
    neutral: 'analytics',
  };

  return (
    <div
      onClick={onClick}
      className={`flex flex-col justify-between p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 shadow-sm hover:shadow-md transition-all ${
        onClick ? 'cursor-pointer hover:bg-surface-bright' : ''
      } ${className}`}
    >
      <div className="flex items-center justify-between text-secondary mb-1">
        <span className="font-caption-ui text-caption-ui uppercase tracking-wider font-semibold text-outline">
          {title}
        </span>
        <div className="flex items-center gap-1">
          {badge}
          {icon && (
            <span className={`material-symbols-outlined text-[18px] ${iconColor}`}>{icon}</span>
          )}
        </div>
      </div>

      <div className="my-space-xs">
        <div className="flex items-baseline gap-2">
          <span className={`font-mono-metric-lg text-mono-metric-lg font-semibold ${valueColor}`}>
            {value}
          </span>
          {unit && (
            <span className="font-body-medium text-body-medium text-on-surface-variant">
              {unit}
            </span>
          )}
          {deltaText && (
            <span className={`font-mono-badge text-mono-badge font-semibold ${deltaColorMap[deltaType]}`}>
              {deltaText}
            </span>
          )}
        </div>
        {subtitle && (
          <p className="font-mono-caption text-mono-caption text-on-surface-variant mt-1 truncate">
            {subtitle}
          </p>
        )}
      </div>

      {trend && (
        <div
          className={`flex items-center gap-1 font-mono-caption text-mono-caption mt-1 ${
            trendDirection === 'up' && (title.includes('Error') || title.includes('Incidents') || title.includes('Latency'))
              ? 'text-error'
              : 'text-on-surface-variant'
          }`}
        >
          <span className="material-symbols-outlined text-[14px]">
            {trendIconMap[trendDirection]}
          </span>
          <span>{trend}</span>
        </div>
      )}

      {indicator}

      {progressPercent !== undefined && !indicator && (
        <div className="w-full bg-surface-container-high h-1.5 rounded-full overflow-hidden mt-1">
          <div
            className={`h-full rounded-full transition-all duration-500 ${progressBarColor}`}
            style={{ width: `${Math.min(100, Math.max(0, progressPercent))}%` }}
          />
        </div>
      )}
    </div>
  );
};
