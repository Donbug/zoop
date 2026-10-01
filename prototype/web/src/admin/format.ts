// 관리자 화면의 시각·수치 표기. 시각은 항상 한국 표준시(KST)로 보여준다.

const kstDateTime = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

const kstDate = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });

function parts(format: Intl.DateTimeFormat, value: Date) {
  return Object.fromEntries(format.formatToParts(value).map((p) => [p.type, p.value]));
}

/** "2026-10-01 07:40:12" (KST). 값이 없거나 읽을 수 없으면 null. */
export function formatKst(value: string | null | undefined, { seconds = false }: { seconds?: boolean } = {}): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const p = parts(kstDateTime, date);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}${seconds ? `:${p.second}` : ""}`;
}

/** 오늘 날짜(KST) "2026-10-01" */
export function todayKst(): string {
  const p = parts(kstDate, new Date());
  return `${p.year}-${p.month}-${p.day}`;
}

const integer = new Intl.NumberFormat("ko-KR");
export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : integer.format(value);
}

export function formatDurationMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value < 1000) return `${Math.round(value)}ms`;
  const seconds = value / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}초`;
  return `${Math.floor(seconds / 60)}분 ${Math.round(seconds % 60)}초`;
}
