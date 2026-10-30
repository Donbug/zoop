import type { ChartPeriod } from '@/types/company';
import type { Event, Impact } from '@/types/company/detail';
import type { GraphResponse } from '@/types/map/graph';
import { exactTime } from '@/util/event-time';
import { formatMoney } from '@/util/format';
export { exactTime } from '@/util/event-time';
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
/**
 * 요청에 쓸 RFC 3339 시각(초 포함, UTC). 초 없는 시각(2026-10-20T00:00+09:00)은 기업·그래프 API가
 * 422로 거절하므로 기준 시점(asOf)으로 주소에 고정할 때 바꾼다.
 */
export const requestTime = (value: string) =>
  new Date(value).toISOString().replace(/\.000Z$/, 'Z');
/**
 * 주소에 graphVersion만 있고 기준 시점이 없다. 백엔드(#358)는 이 경우 그 버전이 처음 공개된 시각을
 * metadata.asOf로 주므로 화면이 그 시각을 asOf로 채운다. 채우기 전에는 차트·타임라인·그래프·문서·재무
 * 조회를 시작하지 않는다. 그 버전으로 답하지 않거나, 채운 시각으로 다시 열 때 409·422면(활성화 경합 등)
 * 열 수 없다고 안내한다.
 */
export const versionOnlyAddress = (
  asOf: string | null,
  version: string | null,
) => !asOf && !!version;
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
    impact.pathStatus !== 'direct_available' ||
    !impact.steps.some(
      (step) => step.id === impact.companyId && step.kind === 'company',
    ) ||
    !impact.steps.some(
      (step) => step.id === impact.issueId && step.kind === 'issue',
    ) ||
    impact.steps.some(
      (step) =>
        (step.id === impact.companyId || step.id === impact.issueId) &&
        step.evidenceIds.length === 0,
    ) ||
    impact.metadata.partial ||
    graph.metadata.partial ||
    impact.metadata.graphVersion !== graph.metadata.graphVersion ||
    Date.parse(impact.metadata.asOf) !== Date.parse(graph.metadata.asOf)
  )
    return [];
  const evidenceIds = new Set(impact.steps.flatMap((step) => step.evidenceIds));
  const edge = graph.edges.find(
    (candidate) =>
      !candidate.derived &&
      candidate.relationType === 'INVOLVES' &&
      candidate.source === impact.issueId &&
      candidate.target === impact.companyId &&
      [...evidenceIds].every((id) => candidate.evidenceIds.includes(id)),
  );
  return edge ? [edge.id] : [];
}
export const safeHref = (value: string | null) =>
  value && /^https?:\/\//i.test(value) ? value : undefined;
export const number = (value: number | null | undefined) =>
  value == null
    ? '미제공'
    : new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 2 }).format(
        value,
      );
/** N-x: 현재가와 같은 통화 표기. 값이 없으면 '미제공'. 원화는 평균 매입가처럼 소수가 있으면 그대로 둔다. */
export const money = (value: number | null | undefined, currency: string) =>
  value == null
    ? '미제공'
    : currency === 'KRW' && !Number.isInteger(value)
      ? `${number(value)}원`
      : formatMoney(value, currency);
