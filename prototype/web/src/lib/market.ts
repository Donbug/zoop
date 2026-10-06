// 시세 표기와 차트 위 사건 표시 규칙(요구 35·36·37).
//  - 금액은 받은 통화 그대로 적는다(환산하지 않음). 원화·엔화는 소수점 없이, 그 밖은 소수 2~4자리.
//  - 등락 글자 표기는 components/domain/status-labels의 PriceChange(색 + 부호 + ▲/▼ + 상승/하락/보합)가 맡는다.
//  - 사건 표시는 일·시각까지 확인된 사건만 둔다. 월·연 정밀도 사건은 하루에 놓을 수 없어 표시하지 않는다.
import type { EventGroup, Period } from "./company-timeline";
import { kstDate } from "./company-timeline";

const unit: Record<string, string> = { KRW: "원", USD: "달러", JPY: "엔" };
const wholeUnits: Record<string, true> = { KRW: true, JPY: true };

export function formatPrice(value: number, currency: string): string {
  if (currency === "KRW") return `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(value)}원`;
  return new Intl.NumberFormat("ko-KR", {
    style: "currency",
    currency,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: wholeUnits[currency] ? 0 : 2,
    maximumFractionDigits: wholeUnits[currency] ? 0 : 4,
  }).format(value);
}

/** 큰 수(거래량·시가총액): 843.1만, 1,620조 */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function formatCompactMoney(value: number, currency: string): string {
  return `${formatCompact(value)} ${unit[currency] ?? currency}`;
}

export type Tone = "up" | "down" | "flat";

export function toneOf(change: number | null | undefined): Tone {
  if (change == null || change === 0) return "flat";
  return change > 0 ? "up" : "down";
}

/** 차트 시각 표기: 일봉은 날짜, 분봉은 거래소 현지 시각(받은 ISO 문자열의 시각 그대로) */
export function pointLabel(iso: string, intraday: boolean): string {
  const [date, rest = ""] = iso.split("T");
  const [, m, d] = (date ?? "").split("-");
  return intraday ? rest.slice(0, 5) : `${Number(m)}월 ${Number(d)}일`;
}

export interface ChartMarker {
  /** 0~1 가로 위치 */
  x: number;
  /** 묶음 키(?open=)들, 최신이 먼저 */
  keys: string[];
  /** 사건 날짜(YYYY-MM-DD)들 */
  dates: string[];
  count: number;
}

const MERGE_DISTANCE = 0.06;

/** 날짜 묶음을 차트 가로 위치에 놓는다. 일봉은 사건 날짜의 거래일(휴장일이면 4일 안의 다음 거래일),
 *  분봉(최근 거래일 하루)은 시각을 아는 사건만 그 시각에, 날짜만 아는 사건은 그 거래일 시작에 둔다. 가까운 표시는 합친다. */
export function placeMarkers(times: string[], intraday: boolean, groups: EventGroup[], period: Period = "1m"): ChartMarker[] {
  const n = times.length;
  if (n === 0) return [];
  const barDates = times.map((t) => t.slice(0, 10));
  const barMs = times.map((t) => Date.parse(t));
  const placed: { x: number; key: string; date: string; count: number }[] = [];
  for (const group of groups) {
    const first = group.items[0];
    if (group.unknown || !first?.eventTime || (first.timePrecision !== "day" && first.timePrecision !== "datetime")) continue;
    const date = period === "1y" && group.start ? group.start.slice(0, 10) : kstDate(first.eventTime);
    if (!date) continue;
    let index = -1;
    if (intraday) {
      const ms = first.timePrecision === "datetime" ? Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(first.eventTime) ? first.eventTime : `${first.eventTime}+09:00`) : NaN;
      if (first.timePrecision !== "datetime") continue;
      if (!Number.isNaN(ms) && ms >= barMs[0]! && ms <= barMs[n - 1]!) {
        index = barMs.reduce((best, t, i) => (Math.abs(t - ms) < Math.abs(barMs[best]! - ms) ? i : best), 0);
      }
    } else if (period === "1y") {
      index = barDates.reduce((best, value, i) => Math.abs(Date.parse(value) - Date.parse(date)) < Math.abs(Date.parse(barDates[best]!) - Date.parse(date)) ? i : best, 0);
    } else if (date >= barDates[0]!) {
      const found = barDates.findIndex((d) => d >= date);
      if (found >= 0 && (Date.parse(barDates[found]!) - Date.parse(date)) / 86_400_000 <= 4) index = found;
    }
    if (index < 0) continue;
    placed.push({ x: n === 1 ? 0.5 : index / (n - 1), key: group.key, date, count: group.items.length });
  }
  placed.sort((a, b) => b.x - a.x);
  const markers: ChartMarker[] = [];
  for (const p of placed) {
    const last = markers.at(-1);
    if (last && Math.abs(last.x - p.x) < MERGE_DISTANCE) {
      last.keys.push(p.key);
      if (!last.dates.includes(p.date)) last.dates.push(p.date);
      last.count += p.count;
    } else markers.push({ x: p.x, keys: [p.key], dates: [p.date], count: p.count });
  }
  return markers;
}
