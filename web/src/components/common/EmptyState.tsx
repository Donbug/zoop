import type { EmptyStateProps } from '@/types/common';

export default function EmptyState({ message }: EmptyStateProps) {
  return <p className="text-sm leading-6 text-zoop-ink">{message}</p>;
}
