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

export type ConfirmDialogProps = {
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** 처리 중에는 두 버튼과 Esc 닫기를 막는다. */
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};
