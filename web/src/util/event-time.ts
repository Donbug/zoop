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

/**
 * 목록 한 줄용 발생 시각. 정밀도가 있으면 그 단위까지만 보이고, 형식을 해석하지 못하면 받은 값을 그대로 둔다.
 * 정밀도가 오지 않으면 정확한 시각만 KST로 바꾼다. 알 수 없으면 null.
 */
export function eventTimeText(
  value: string | null | undefined,
  precision?: TimePrecision | null,
) {
  if (!value || precision === 'unknown') return null;
  if (!precision) return exactTime(value) ? formatKst(value) : value;
  const time = formatTimelineTime(value, precision);
  return time === '시점 미상' ? value : time;
}
