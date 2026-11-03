import React from 'react';
import { Button } from './Button';

export interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon = 'inbox',
  title,
  description,
  actionLabel,
  onAction,
  className = '',
}) => {
  return (
    <div className={`flex flex-col items-center justify-center p-space-2xl text-center bg-surface-container-lowest rounded-xl shadow-sm border border-outline-variant/30 ${className}`}>
      <div className="w-12 h-12 rounded-xl bg-surface-container flex items-center justify-center text-secondary mb-space-sm">
        <span className="material-symbols-outlined text-[28px]">{icon}</span>
      </div>
      <h3 className="font-title-md text-title-md text-on-surface font-semibold mb-1">
        {title}
      </h3>
      {description && (
        <p className="font-body-default text-body-default text-on-surface-variant max-w-md mb-space-md">
          {description}
        </p>
      )}
      {actionLabel && onAction && (
        <Button variant="primary" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
};

