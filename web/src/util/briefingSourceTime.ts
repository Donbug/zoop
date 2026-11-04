import { briefingTime } from './briefingTime';

/** D-BRF-01/02: publication day and first observation never imply an exact publication instant. */
export type PrioritySourceTime = {
  publishedAt: string | null;
  publishedDate?: string | null;
  availableAt?: string | null;
  eligibilityBasis?: string | null;
};

export function prioritySourceAvailable(source: PrioritySourceTime): number {
  if (source.publishedAt !== null) return Date.parse(source.publishedAt);
  if (source.eligibilityBasis !== 'first_observed' || !source.publishedDate || !source.availableAt)
    return NaN;
  const day = source.publishedDate;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || new Date(day + 'T00:00:00Z').toISOString().slice(0,10) !== day)
    return NaN;
  const observed = Date.parse(source.availableAt);
  if (!Number.isFinite(observed) || day > new Date(observed + 9 * 3600000).toISOString().slice(0,10))
    return NaN;
  return observed;
}

export function prioritySourceTime(source: PrioritySourceTime): string {
  return source.publishedAt !== null
    ? briefingTime(source.publishedAt)
    : `게시일 ${source.publishedDate} · 최초 수집 ${briefingTime(source.availableAt)}`;
}
