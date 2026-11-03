import React from 'react';

export interface LoadingSpinnerProps {
  message?: string;
  size?: 'sm' | 'md' | 'lg';
  fullScreen?: boolean;
  className?: string;
}

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({
  message = 'Loading telemetry payload...',
  size = 'md',
  fullScreen = false,
  className = '',
}) => {
  const sizeMap = {
    sm: 'text-[18px]',
    md: 'text-[24px]',
    lg: 'text-[32px]',
  };

  const containerClasses = fullScreen
    ? 'fixed inset-0 z-50 bg-background/80 backdrop-blur-sm'
    : '';

  return (
    <div className={`flex flex-col items-center justify-center p-space-xl gap-space-sm text-secondary ${containerClasses} ${className}`}>
      <span className={`material-symbols-outlined ${sizeMap[size]} animate-spin text-primary`}>
        progress_activity
      </span>
      {message && (
        <span className="font-mono-caption text-mono-caption text-on-surface-variant animate-pulse">
          {message}
        </span>
      )}
    </div>
  );
};

