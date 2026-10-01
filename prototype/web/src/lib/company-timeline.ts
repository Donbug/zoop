// 기업 상세 타임라인의 기간·날짜 묶음 규칙(요구 37·38, 명세 v1.2 FS040·D04·D05).
//  - 조회 범위는 한국 시간의 조회 시각을 공통 종료 시각으로 고정하고, 1일은 그날 00시부터, 1개월·1년은 달력상 한 달·한 해 전
//    같은 시각부터다(대응 날짜가 없으면 그 달 말일). 차트와 타임라인이 같은 범위를 각각 요청한다. 종료 시각 뒤로 잡힌(예정) 사건은 없다.
//  - 발생 날짜만 아는 사건은 그 날짜 묶음에 두고 상세에 '시각 미상'을 적는다. 발생 날짜도 모르면(월·연만 알거나 모름) 시각을
//    지어내지 않고 '발생 시점 미상' 묶음에 따로 둔다. 이 묶음은 보도 시각(기사 발행)이 범위 안인 사건만 담고, 카드에는 보도 시각을
//    '보도'로 적는다(서버 unknownTimeItems). 보도 시각은 범위 판별에만 쓰고 발생일로 보이지 않는다.
//  - 같은 날짜(정밀도 그대로)의 사건은 한 묶음이다. 사건을 합치지 않고 묶음 안에 사건별 카드로 펼친다.
import type { Schemas } from "@/api/client";
import { formatEventTime } from "./labels";

export type Period = "1d" | "1m" | "1y";
export const periods: Period[] = ["1d", "1m", "1y"];
export const defaultPeriod: Period = "1m";
export const periodLabel: Record<Period, string> = { "1d": "1일", "1m": "1개월", "1y": "1년" };
/** 빈 상태 문장용: '최근 1개월 동안' */
export const periodPhrase: Record<Period, string> = { "1d": "오늘", "1m": "최근 1개월 동안", "1y": "최근 1년 동안" };

export function parsePeriod(value: string | null): Period {
  return value === "1d" || value === "1m" || value === "1y" ? value : defaultPeriod;
}

/** 지금 KST 날짜 YYYY-MM-DD */
export function todayKst(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** 기간 시작일(포함). 1개월·1년 전 같은 날이 없으면 그 달 말일(3월 31일의 1개월 전 → 2월 말일). */
export function periodFrom(period: Period, today: string): string {
  if (period === "1d") return today;
  const [y, m, d] = today.split("-").map(Number) as [number, number, number];
  const months = period === "1m" ? 1 : 12;
  const index = y * 12 + (m - 1) - months;
  const year = Math.floor(index / 12);
  const month = (index % 12) + 1;
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(Math.min(d, lastDay)).padStart(2, "0")}`;
}

/** ISO 시각의 KST 날짜(YYYY-MM-DD). 오프셋이 없으면 KST로 읽는다. */
export function kstDate(iso: string): string | null {
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) || !iso.includes("T") ? iso : `${iso}+09:00`);
  return Number.isNaN(date.getTime()) ? null : todayKst(date);
}

/** 차트·타임라인이 함께 쓰는 조회 범위. from·to는 +09:00 오프셋 ISO 시각, today는 to의 KST 날짜. */
export interface DetailRange {
  period: Period;
  from: string;
  to: string;
  today: string;
}

export function detailRange(period: Period, now = new Date()): DetailRange {
  const today = todayKst(now);
  const time = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(now);
  const to = `${today}T${time}+09:00`;
  const from = period === "1d" ? `${today}T00:00:00+09:00` : `${periodFrom(period, today)}T${time}+09:00`;
  return { period, from, to, today };
}

/** 가장 최근 사건(또는 보도)이 들어가는 가장 좁은 넓은 기간. 1년으로도 안 되면 null. */
export function widerPeriodFor(date: string, current: Period, today: string): Period | null {
  return periods.slice(periods.indexOf(current) + 1).find((p) => periodFrom(p, today) <= date) ?? null;
}

/** 서버가 준 최근 발생 시각(YYYY, YYYY-MM, YYYY-MM-DD…)이 끝나는 날. 월·연 정밀도는 그 기간의 마지막 날이다. */
export function eventEndDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const datePart = value.slice(0, 10);
  const [y, m] = datePart.split("-").map(Number) as [number, number | undefined];
  if (datePart.length === 4) return `${y}-12-31`;
  if (datePart.length === 7 && m) return `${datePart}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, "0")}`;
  return datePart;
}

export const UNKNOWN_GROUP = "unknown";

export interface EventGroup {
  /** 주소(?open=)에 쓰는 묶음 키: 발생 시각 표시값 또는 'unknown' */
  key: string;
  /** 화면 표시 날짜 */
  label: string;
  unknown: boolean;
  items: Schemas["EventSummary"][];
}

/** 서버 순서(발생 시각 최신순)를 지키며 같은 날짜끼리 묶고, 발생 시점 미상 묶음을 맨 뒤에 둔다. */
export function groupEvents(items: Schemas["EventSummary"][], undated: Schemas["EventSummary"][]): EventGroup[] {
  const groups: EventGroup[] = [];
  for (const e of items) {
    const label = formatEventTime(e.eventTime, e.timePrecision);
    const last = groups.at(-1);
    if (last && last.key === label) {
      last.items.push(e);
      continue;
    }
    groups.push({ key: label, label, unknown: false, items: [e] });
  }
  if (undated.length > 0) groups.push({ key: UNKNOWN_GROUP, label: "발생 시점 미상", unknown: true, items: undated });
  return groups;
}
