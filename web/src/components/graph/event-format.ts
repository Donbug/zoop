import type { TimePrecision } from '@/types/map/event';

export function formatEventTime(
  value: string | null,
  precision: TimePrecision,
) {
  if (!value || precision === 'unknown') return '발생 시각 미상';
  // A year/month/day must never become a made-up midnight timestamp.
  const parts = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/.exec(value);
  if (!parts) return '발생 시각 미상';
  if (precision === 'year') return `${parts[1]}년 · 연도 단위`;
  if (precision === 'month' && parts[2])
    return `${parts[1]}년 ${Number(parts[2])}월 · 월 단위`;
  if (precision === 'day' && parts[3])
    return `${parts[1]}.${parts[2]}.${parts[3]} · 날짜 단위`;
  if (precision === 'datetime')
    return formatPublishedAt(value) ?? '발생 시각 미상';
  return '발생 시각 미상';
}

export function formatPublishedAt(value: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  return `${new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))} KST`;
}

export function safeArticleUrl(value: string | null) {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
