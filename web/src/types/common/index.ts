import type { ReactNode } from 'react';

export type PageShellProps = {
  title: string;
  children: ReactNode;
};

export type PageSectionProps = PageShellProps;

export type EmptyStateProps = {
  message: string;
};

export type QueryChanges = Record<string, string | null>;

export type QueryUpdateOptions = {
  replace?: boolean;
};

export type ErrorNoticeProps = {
  title: string;
  message?: string;
  onRetry?: () => void;
  retryLabel?: string;
  retryDisabled?: boolean;
};
