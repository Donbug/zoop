import type { ChartPeriod } from '@/types/company';
import { exactTime, legacyTimeRange, periods } from './detail-model';

/** D-COM-05: prototype eventEndDate, used only for range selection, never an invented event timestamp. */
export function eventRangeDate(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  if (exactTime(value))
    return new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 10);
  if (/^\d{4}$/.test(value)) return `${value}-12-31`;
  if (/^\d{4}-\d{2}$/.test(value)) {
    const [year, month] = value.split('-').map(Number);
    if (month < 1 || month > 12) return null;
    return `${value}-${new Date(Date.UTC(year, month, 0)).getUTCDate()}`;
  }
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value))
    ? value
    : null;
}

/** D-COM-05 39/새6: share main's existing calendar boundaries; widen period without changing asOf. */
export function widerCompanyPeriod(
  value: string | null | undefined,
  current: ChartPeriod,
  asOf: string | null,
  currentFrom?: string | null,
): ChartPeriod | null {
  if (!asOf || !exactTime(asOf) || !value) return null;
  const date = eventRangeDate(value);
  if (!date || date > eventRangeDate(asOf)!) return null;
  const fits = (period: ChartPeriod, from?: string | null) => {
    const lower = from ?? legacyTimeRange(asOf, period).from;
    return exactTime(value)
      ? Date.parse(value) >= Date.parse(lower) &&
          Date.parse(value) <= Date.parse(asOf)
      : date >= eventRangeDate(lower)!;
  };
  if (fits(current, currentFrom)) return null;
  return (
    periods
      .slice(periods.findIndex((p) => p.value === current) + 1)
      .find((p) => fits(p.value))?.value ?? null
  );
}
