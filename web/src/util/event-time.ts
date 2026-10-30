import type { TimePrecision } from '@/types/map/event';
import { formatKst } from './format';

// Shared without changing the existing graph/reference-time validation.
export const exactTime = (value: string | null | undefined) =>
  !!value &&
  /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
  Number.isFinite(Date.parse(value));

/** D-COM-01 N-k: prototype precision branches, using main's KST formatter. */
export function formatTimelineTime(
  value: string | null | undefined,
  precision: TimePrecision | null | undefined,
) {
  if (!value || !precision || precision === 'unknown') return '시점 미상';
  if (precision === 'datetime')
    return exactTime(value) ? formatKst(value) : '시점 미상';
  const parts = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/.exec(value);
  if (!parts) return '시점 미상';
  if (precision === 'year') return parts[1];
  if (precision === 'month' && parts[2]) return `${parts[1]}-${parts[2]}`;
  if (precision === 'day' && parts[3])
    return `${parts[1]}-${parts[2]}-${parts[3]}`;
  return '시점 미상';
}
