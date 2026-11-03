import React from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'surface' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: string; // Material symbol icon name
  iconRight?: string;
  loading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'secondary',
  size = 'md',
  icon,
  iconRight,
  loading = false,
  className = '',
  disabled,
  ...props
}) => {
  const baseClasses = 'inline-flex items-center justify-center gap-1.5 font-body-medium transition-colors select-none rounded-lg focus:outline-none';

  const sizeClasses: Record<ButtonSize, string> = {
    sm: 'h-7 px-2.5 text-caption-ui',
    md: 'h-8 px-3 text-body-medium',
    lg: 'h-9 px-4 text-body-medium',
  };

  const variantClasses: Record<ButtonVariant, string> = {
    primary: 'bg-primary hover:bg-primary-container text-on-primary shadow-sm active:scale-[0.99]',
    secondary: 'bg-surface-container hover:bg-surface-container-high text-on-surface shadow-sm border border-outline-variant/30',
    surface: 'bg-surface-container-high hover:bg-surface-container-highest text-on-surface',
    ghost: 'bg-transparent hover:bg-surface-container-low text-secondary hover:text-on-surface',
    danger: 'bg-error hover:bg-error/90 text-on-error shadow-sm',
  };

  const disabledClasses = disabled || loading ? 'opacity-50 cursor-not-allowed pointer-events-none' : 'cursor-pointer';

  return (
    <button
      className={`${baseClasses} ${sizeClasses[size]} ${variantClasses[variant]} ${disabledClasses} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <span className="material-symbols-outlined text-[16px] animate-spin">progress_activity</span>
      ) : icon ? (
        <span className="material-symbols-outlined text-[16px]">{icon}</span>
      ) : null}
      {children && <span>{children}</span>}
      {!loading && iconRight ? (
        <span className="material-symbols-outlined text-[14px]">{iconRight}</span>
      ) : null}
    </button>
  );
};

