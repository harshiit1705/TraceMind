import React from 'react';

export interface SearchInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  onClear?: () => void;
  shortcutBadge?: string;
}

export const SearchInput: React.FC<SearchInputProps> = ({
  placeholder = 'Search traces, span IDs, services, logs (Cmd+K)',
  shortcutBadge = '⌘K',
  value,
  onChange,
  onClear,
  className = '',
  ...props
}) => {
  return (
    <div className={`relative w-full ${className}`}>
      <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-[18px] text-outline pointer-events-none select-none">
        search
      </span>
      <input
        type="text"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className="w-full h-8 pl-9 pr-14 bg-surface text-on-surface placeholder:text-outline border border-outline-variant/40 rounded-lg text-body-default font-body-default focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all"
        {...props}
      />
      {value && onClear ? (
        <button
          type="button"
          onClick={onClear}
          className="absolute right-9 top-1/2 -translate-y-1/2 text-outline hover:text-on-surface p-0.5 rounded transition-colors"
          title="Clear search"
        >
          <span className="material-symbols-outlined text-[16px]">close</span>
        </button>
      ) : null}
      {shortcutBadge && (
        <kbd className="absolute right-2 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-mono-caption font-mono-caption text-outline bg-surface-container border border-outline-variant/30 rounded select-none pointer-events-none">
          {shortcutBadge}
        </kbd>
      )}
    </div>
  );
};

