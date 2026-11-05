// D-BRF-01·02: 회차에 외곽 경계 하나를 두고, 내부는 제목·행·구분선으로 나눈다.
// 회차 안의 블록(헤더·섹션·접기 영역)은 모두 아래쪽에만 선을 긋고, 마지막 블록은 긋지 않는다.

export const CARD =
  'mt-6 rounded-xl border border-zoop-border bg-zoop-surface p-6 max-sm:p-4';
export const SECTION =
  'my-6 border-b border-zoop-border pb-6 last:mb-0 last:border-b-0 last:pb-0';
/** h2 회차 제목(text-title) > h3 섹션 제목 > h4 소제목 */
export const SECTION_TITLE = 'mb-4 text-title-sm font-bold leading-snug';
export const SUBSECTION_TITLE = 'mb-3 text-lead font-bold';
export const DISCLOSURE =
  'border-b border-zoop-border py-3 last:border-b-0 last:pb-0';
export const ISSUE_LIST = 'space-y-5';
export const ISSUE_ROW =
  'border-t border-zoop-border pt-5 first:border-t-0 first:pt-0';
export const ISSUE_SUMMARY = 'min-h-11 cursor-pointer list-none py-1';
/** 펼친 본문은 행 구분선과 겹치지 않게 왼쪽 선과 들여쓰기로 이슈에 묶는다. */
export const ISSUE_BODY =
  'mt-4 space-y-6 border-l-2 border-zoop-border pl-4 max-sm:pl-3';
export const EMPTY =
  'rounded-panel bg-zoop-card p-4 text-body leading-relaxed text-zoop-muted';
export const NOTE =
  'text-caption leading-relaxed text-zoop-muted [overflow-wrap:anywhere]';
export const BODY =
  'text-body leading-[1.7] whitespace-pre-wrap [overflow-wrap:anywhere]';
export const STATUS_PILL =
  'inline-flex shrink-0 items-center rounded-panel bg-zoop-card px-2 py-1 text-caption font-medium text-zoop-ink';
export const FOCUS_RING =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink';
export const PRIMARY_BUTTON = `mt-4 min-h-9 rounded-md bg-zoop-ink px-4 py-2.5 text-caption font-semibold text-zoop-on-ink ${FOCUS_RING}`;
