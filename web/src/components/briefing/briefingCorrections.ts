import type { BriefingResponse } from '@/types/briefing';

type Correction = BriefingResponse['corrections'][number];

/** N-h: 프로토타입 status-labels.tsx의 disclaimerText */
export const BRIEFING_DISCLAIMER = '본 정보는 참고용이며 투자 권유가 아니에요.';

/** 55: 회차·이슈 정정을 나눈다. eventId가 없거나 화면에 없는 이슈의 정정은 회차 정정으로 둔다. */
export function splitCorrections(
  corrections: Correction[],
  shownEventIds: string[],
) {
  const shown = new Set(shownEventIds);
  const byIssue = new Map<string, Correction[]>();
  const round: Correction[] = [];
  for (const correction of corrections) {
    if (correction.eventId && shown.has(correction.eventId))
      byIssue.set(correction.eventId, [
        ...(byIssue.get(correction.eventId) ?? []),
        correction,
      ]);
    else round.push(correction);
  }
  return { round, byIssue };
}
