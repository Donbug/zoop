import type { ChartPeriod } from '@/types/company';
import type { Event, Impact } from '@/types/company/detail';
import type { GraphResponse } from '@/types/map/graph';
export const periods: {
  value: ChartPeriod;
  label: string;
  interval: string;
  /** 화면에 보이는 시간 버킷 이름(FS041) */
  bucket: string;
}[] = [
  { value: '1d', label: '1일', interval: '5m', bucket: '5분' },
  { value: '1w', label: '1주', interval: '1h', bucket: '1시간' },
  { value: '1m', label: '1개월', interval: '1d', bucket: '일' },
  { value: '1y', label: '1년', interval: '1wk', bucket: '주' },
];
export const exactTime = (value: string | null | undefined) =>
  !!value &&
  /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
  Number.isFinite(Date.parse(value));
/**
 * 요청에 쓸 RFC 3339 시각(초 포함, UTC). 토스 가격 봉은 초 없는 시각(2026-10-20T00:00+09:00)을 주는데,
 * 기업·그래프 API는 이를 422로 거절하므로 기준 시점(asOf)으로 쓸 때 바꾼다.
 */
export const requestTime = (value: string) =>
  new Date(value).toISOString().replace(/\.000Z$/, 'Z');
const BAR_MS: Record<string, number> = {
  '5m': 5 * 60 * 1000,
  '1h': 60 * 60 * 1000,
  '1d': 24 * 60 * 60 * 1000,
  '1wk': 7 * 24 * 60 * 60 * 1000,
};
/**
 * 가격 봉 시각은 구간 시작 시각이다(#236). 마지막 봉으로 기준 시점을 정할 때는 그 봉이 끝나는
 * 시각을 쓰되 지금보다 늦지 않게 한다. 시작 시각을 쓰면 오늘 일봉이 00:00으로 잡혀 오늘이 빠진다.
 */
export function barEnd(time: string, interval: string, now = Date.now()) {
  const end = Date.parse(time) + (BAR_MS[interval] ?? 0);
  return requestTime(new Date(Math.min(end, now)).toISOString());
}
export function bucketKey(
  event: Pick<Event, 'eventTime' | 'timePrecision'>,
  period: ChartPeriod,
): string {
  if (
    !event.eventTime ||
    ['unknown', 'year', 'month'].includes(event.timePrecision)
  )
    return '시점 미상·정밀도 부족';
  if (
    event.timePrecision !== 'datetime' &&
    (period === '1d' || period === '1w')
  )
    return `${event.eventTime.slice(0, 10)} · 일 정밀도`;
  if (event.timePrecision !== 'datetime' && period === '1m')
    return event.eventTime.slice(0, 10);
  if (event.timePrecision === 'datetime' && !exactTime(event.eventTime))
    return '시점 미상·정밀도 부족';
  const time = Date.parse(
    event.timePrecision === 'day'
      ? `${event.eventTime.slice(0, 10)}T00:00:00+09:00`
      : event.eventTime,
  );
  if (period === '1d' || period === '1w')
    return new Date(
      Math.floor(time / (period === '1d' ? 300000 : 3600000)) *
        (period === '1d' ? 300000 : 3600000),
    ).toISOString();
  const day = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(time));
  if (period === '1y') {
    const date = new Date(`${day}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
    return `${date.toISOString().slice(0, 10)} 주`;
  }
  return day;
}
export function timeRange(asOf: string, period: '1d'): { to: string };
export function timeRange(
  asOf: string,
  period: Exclude<ChartPeriod, '1d'>,
): { from: string; to: string };
export function timeRange(
  asOf: string,
  period: ChartPeriod,
): { to: string } | { from: string; to: string };
export function timeRange(asOf: string, period: ChartPeriod) {
  if (period === '1d') return { to: new Date(asOf).toISOString() };
  return legacyTimeRange(asOf, period);
}

/** Deployment fallback only; the exchange session is determined by the server. */
export function legacyTimeRange(asOf: string, period: ChartPeriod) {
  // Calendar periods follow the API's Asia/Seoul date boundary, even at KST midnight.
  const kstOffset = 9 * 60 * 60 * 1000;
  const end = new Date(asOf),
    start = new Date(Date.parse(asOf) + kstOffset);
  if (period === '1d') start.setUTCDate(start.getUTCDate() - 1);
  if (period === '1w') start.setUTCDate(start.getUTCDate() - 7);
  if (period === '1m') {
    const day = start.getUTCDate();
    start.setUTCDate(1);
    start.setUTCMonth(start.getUTCMonth() - 1);
    const last = new Date(
      Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0),
    ).getUTCDate();
    start.setUTCDate(Math.min(day, last));
  }
  if (period === '1y') {
    const month = start.getUTCMonth();
    start.setUTCFullYear(start.getUTCFullYear() - 1);
    if (start.getUTCMonth() !== month) start.setUTCDate(0);
  }
  return {
    from: new Date(start.getTime() - kstOffset).toISOString(),
    to: end.toISOString(),
  };
}
export function impactEdges(
  graph: GraphResponse,
  impact: Impact | null,
): string[] {
  if (
    !impact ||
    !impact.steps.some(
      (step) => step.id === impact.companyId && step.kind === 'company',
    ) ||
    !impact.steps.some(
      (step) => step.id === impact.issueId && step.kind === 'issue',
    ) ||
    impact.metadata.partial ||
    graph.metadata.partial ||
    impact.metadata.graphVersion !== graph.metadata.graphVersion ||
    Date.parse(impact.metadata.asOf) !== Date.parse(graph.metadata.asOf)
  )
    return [];
  const edges: string[] = [];
  for (let i = 1; i < impact.steps.length; i++) {
    const a = impact.steps[i - 1].id,
      b = impact.steps[i].id;
    for (const e of graph.edges)
      if (
        !e.derived &&
        e.assertionStatus === 'confirmed' &&
        e.evidenceIds.some(
          (evidence) =>
            impact.steps[i - 1].evidenceIds.includes(evidence) ||
            impact.steps[i].evidenceIds.includes(evidence),
        ) &&
        e.relationType !== 'SHARES_ISSUE' &&
        ((e.source === a && e.target === b) ||
          (e.source === b && e.target === a))
      )
        edges.push(e.id);
  }
  return [...new Set(edges)];
}
export const safeHref = (value: string | null) =>
  value && /^https?:\/\//i.test(value) ? value : undefined;
export const number = (value: number | null | undefined) =>
  value == null
    ? '미제공'
    : new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 2 }).format(
        value,
      );
