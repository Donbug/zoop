// 브리핑 화면(D-BRF-01·02) 공통 Tailwind 클래스. #169 시각 기준값을 zoop 토큰으로 쓴다.

export const CARD =
  'mt-[18px] rounded-xl border border-zoop-border bg-zoop-surface p-6 shadow-sm max-sm:p-4';
export const SECTION = 'my-3 rounded-lg bg-zoop-card p-4';
export const SECTION_TITLE = 'mb-3 text-caption font-bold';
export const EMPTY =
  'rounded-md border border-dashed border-zoop-border bg-zoop-card p-[18px] text-caption leading-relaxed text-zoop-muted';
export const NOTE =
  'text-caption leading-relaxed text-zoop-muted [overflow-wrap:anywhere]';
export const BODY =
  'text-body leading-[1.7] whitespace-pre-wrap [overflow-wrap:anywhere]';
export const STATUS_PILL =
  'shrink-0 rounded-full border border-zoop-border px-2 py-[3px] text-caption font-semibold text-zoop-muted';
export const FOCUS_RING =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink';
export const PRIMARY_BUTTON = `mt-4 min-h-9 rounded-md bg-zoop-ink px-4 py-2.5 text-caption font-semibold text-zoop-on-ink ${FOCUS_RING}`;
