// FS040/FS041: 같은 공개 기준 시점·기간을 차트, 타임라인, 관계 그래프에 사용한다.
import type { Schemas } from "@/api/client";
import { formatEventTime } from "./labels";

export type Period = "1d" | "1w" | "1m" | "1y";
export const periods: Period[] = ["1d", "1w", "1m", "1y"];
export const defaultPeriod: Period = "1m";
export const periodLabel: Record<Period, string> = { "1d": "1일", "1w": "1주", "1m": "1개월", "1y": "1년" };
export const periodPhrase: Record<Period, string> = { "1d": "오늘", "1w": "최근 1주 동안", "1m": "최근 1개월 동안", "1y": "최근 1년 동안" };
export const resolutionLabel: Record<Period, string> = { "1d": "5분", "1w": "시간", "1m": "일", "1y": "주" };
export function parsePeriod(value: string | null): Period {
  return periods.includes(value as Period) ? value as Period : defaultPeriod;
}
export function parseAsOf(value: string | null): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
export function todayKst(now = new Date(), timeZone = "Asia/Seoul"): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}
export function exchangeZone(companyId: string): string {
  return /^(NASDAQ|NYSE|AMEX):/.test(companyId) ? "America/New_York" : companyId.startsWith("TSE:") ? "Asia/Tokyo" : "Asia/Seoul";
}
export function periodFrom(period: Period, today: string): string {
  if (period === "1d") return today;
  if (period === "1w") return new Date(Date.parse(`${today}T12:00:00Z`) - 7 * 86_400_000).toISOString().slice(0, 10);
  const [y, m, d] = today.split("-").map(Number) as [number, number, number];
  const index = y * 12 + m - 1 - (period === "1m" ? 1 : 12);
  const year = Math.floor(index / 12);
  const month = ((index % 12) + 12) % 12 + 1;
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(Math.min(d, lastDay)).padStart(2, "0")}`;
}
export function kstDate(iso: string): string | null {
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) || !iso.includes("T") ? iso : `${iso}+09:00`);
  return Number.isNaN(date.getTime()) ? null : todayKst(date);
}
export interface DetailRange { period: Period; from: string; to: string; today: string; timeZone?: string }
export function detailRange(period: Period, now = new Date(), timeZone = "Asia/Seoul"): DetailRange {
  const today = todayKst(now, timeZone);
  const formatter = new Intl.DateTimeFormat("en-GB", { timeZone, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", timeZoneName: "longOffset" });
  const parts = formatter.formatToParts(now);
  const get = (name: Intl.DateTimeFormatPartTypes) => parts.find(p => p.type === name)?.value ?? "00";
  const offset = get("timeZoneName").replace("GMT", "") || "+00:00";
  const time = `${get("hour")}:${get("minute")}:${get("second")}`;
  const from = `${periodFrom(period, today)}T${period === "1d" ? "00:00:00" : time}${offset}`;
  return { period, from, to: now.toISOString(), today, timeZone };
}
export function widerPeriodFor(date: string, current: Period, today: string): Period | null {
  return periods.slice(periods.indexOf(current) + 1).find(p => periodFrom(p, today) <= date) ?? null;
}
export function eventEndDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const datePart = value.slice(0, 10);
  const [y, m] = datePart.split("-").map(Number) as [number, number | undefined];
  if (datePart.length === 4) return `${y}-12-31`;
  if (datePart.length === 7 && m) return `${datePart}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, "0")}`;
  return datePart;
}
export const UNKNOWN_GROUP = "unknown";
export interface EventGroup { key: string; label: string; unknown: boolean; items: Schemas["EventSummary"][]; start?: string }

/** Never invent a minute for a date-only event. Year buckets use the ISO week's Monday. */
export function eventBucket(event: Schemas["EventSummary"], period: Period, timeZone = "Asia/Seoul") {
  if (!event.eventTime || !["day", "datetime"].includes(event.timePrecision)) return null;
  const date = event.timePrecision === "day" ? event.eventTime.slice(0, 10) : todayKst(new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(event.eventTime) ? event.eventTime : `${event.eventTime}+09:00`), timeZone);
  if (period === "1y") {
    const monday = new Date(`${date}T12:00:00Z`);
    monday.setUTCDate(monday.getUTCDate() - (monday.getUTCDay() + 6) % 7);
    const start = monday.toISOString().slice(0, 10);
    return { key: start, label: `${start} 주`, start };
  }
  if (period === "1m" || event.timePrecision === "day") return { key: date, label: formatEventTime(date, "day"), start: date };
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(event.eventTime) ? event.eventTime : `${event.eventTime}+09:00`));
  const [hour, minute] = parts.split(":");
  const bucketTime = `${hour}:${period === "1w" ? "00" : String(Math.floor(Number(minute) / 5) * 5).padStart(2, "0")}`;
  return { key: `${date}T${bucketTime}`, label: `${formatEventTime(date, "day")} ${bucketTime}`, start: event.eventTime };
}
export function groupEvents(items: Schemas["EventSummary"][], undated: Schemas["EventSummary"][], period: Period = "1m", timeZone = "Asia/Seoul"): EventGroup[] {
  const groups = new Map<string, EventGroup>();
  for (const event of items) {
    const bucket = eventBucket(event, period, timeZone);
    if (!bucket) { undated = [...undated, event]; continue; }
    const group = groups.get(bucket.key);
    if (group) group.items.push(event);
    else groups.set(bucket.key, { ...bucket, unknown: false, items: [event] });
  }
  const result = [...groups.values()];
  if (undated.length) result.push({ key: UNKNOWN_GROUP, label: "발생 시점 미상", unknown: true, items: undated });
  return result;
}

export function companySwitchUrl(companyId: string, params: URLSearchParams): string {
  const next = new URLSearchParams(params);
  for (const key of ["issue", "open", "bucket"]) next.delete(key);
  return `/companies/${encodeURIComponent(companyId)}${next.size ? `?${next}` : ""}`;
}
