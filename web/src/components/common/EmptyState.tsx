import type { EmptyStateProps } from '@/types/common';

export default function EmptyState({ message }: EmptyStateProps) {
  return <p className="text-sm leading-6 text-gray-500">{message}</p>;
}
