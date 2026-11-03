import React from 'react';

export type BadgeVariant = 'default' | 'primary' | 'secondary' | 'error' | 'outline' | 'beta';

export interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
  isMono?: boolean;
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  className = '',
  isMono = true,
}) => {
  const baseClasses = 'inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-medium select-none';
  const fontClass = isMono ? 'font-mono-badge text-mono-badge' : 'font-caption-ui text-caption-ui';

  const variantClasses: Record<BadgeVariant, string> = {
    default: 'bg-surface-container text-on-surface-variant',
    primary: 'bg-primary-fixed text-on-primary-fixed-variant',
    secondary: 'bg-secondary-container text-on-secondary-container',
    error: 'bg-error-container text-on-error-container',
    outline: 'bg-transparent border border-outline-variant/40 text-secondary',
    beta: 'bg-primary-fixed text-on-primary-fixed-variant uppercase tracking-wider',
  };

  return (
    <span className={`${baseClasses} ${fontClass} ${variantClasses[variant]} ${className}`}>
      {children}
    </span>
  );
};

