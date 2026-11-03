import React from 'react';

export interface PageHeaderProps {
  category?: string;
  categoryIcon?: string;
  categoryBadge?: React.ReactNode;
  title: string;
  titleBadge?: React.ReactNode;
  subtitle?: string;
  actions?: React.ReactNode;
  className?: string;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  category,
  categoryIcon,
  categoryBadge,
  title,
  titleBadge,
  subtitle,
  actions,
  className = '',
}) => {
  return (
    <div className={`flex flex-col lg:flex-row lg:items-end justify-between gap-space-md mb-space-lg ${className}`}>
      <div className="flex flex-col gap-space-xxs">
        {category && (
          <div className="flex items-center gap-space-xs text-secondary font-mono-caption text-mono-caption uppercase tracking-wider font-semibold mb-0.5">
            {categoryIcon && (
              <span className="material-symbols-outlined text-[15px] text-primary">{categoryIcon}</span>
            )}
            <span>{category}</span>
            {categoryBadge && (
              <>
                <span className="text-outline">/</span>
                {categoryBadge}
              </>
            )}
          </div>
        )}
        <div className="flex items-center gap-space-sm flex-wrap">
          <h1 className="font-headline-md text-headline-md text-on-surface tracking-tight font-semibold">
            {title}
          </h1>
          {titleBadge}
        </div>
        {subtitle && (
          <p className="font-body-default text-body-default text-on-surface-variant max-w-3xl mt-0.5">
            {subtitle}
          </p>
        )}
      </div>

      {actions && (
        <div className="flex flex-wrap items-center gap-space-xs self-start lg:self-auto shrink-0">
          {actions}
        </div>
      )}
    </div>
  );
};

