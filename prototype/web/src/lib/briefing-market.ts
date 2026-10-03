// 브리핑 시장 지표 표기(FS031). 값은 BFF가 회차를 만들 때 받아 저장한 것이라 화면이 다시 계산하지 않는다.
//  - 지수는 포인트(소수 2자리), 환율은 소수 2자리 + 원. 환산·반올림으로 값을 바꾸지 않는다.
//  - 기준 표기는 실제로 쓴 관측만 적는다: 종가는 날짜, 환율은 날짜와 시각. 비교 기준(전 거래일)도 날짜를 밝힌다.
import type { Schemas } from "@/api/client";

export type Indicator = Schemas["MarketIndicator"];

const decimals = new Intl.NumberFormat("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatIndicatorValue(value: number, unit: Indicator["unit"]): string {
  const text = decimals.format(value);
  return unit === "KRW" ? `${text}원` : text;
}

/** 'YYYY-MM-DD'(KST 날짜) → '10월 2일' */
export function monthDay(date: string): string {
  return `${Number(date.slice(5, 7))}월 ${Number(date.slice(8, 10))}일`;
}

const clockFormat = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false });

/** ISO 시각 → KST 'HH:mm' */
export function kstClock(iso: string): string {
  const parts = clockFormat.formatToParts(new Date(iso));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("hour")}:${get("minute")}`;
}

/** 값이 어느 관측인지: '10월 2일 종가' / '10월 3일 06:15 기준' */
export function observedBasis(indicator: Indicator): string | null {
  if (!indicator.observedDate) return null;
  const day = monthDay(indicator.observedDate);
  if (indicator.valueKind === "close") return `${day} 종가`;
  return indicator.observedAt ? `${day} ${kstClock(indicator.observedAt)} 기준` : `${day} 기준`;
}

/** 변화를 잰 기준: '10월 1일 종가 대비' / '10월 2일 15:30 대비' */
export function baselineBasis(indicator: Indicator): string | null {
  const baseline = indicator.baseline;
  if (!baseline) return null;
  return baseline.at ? `${monthDay(baseline.date)} ${kstClock(baseline.at)} 대비` : `${monthDay(baseline.date)} 종가 대비`;
}
