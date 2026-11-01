import type { PersonalAiAnalysis } from '@/types/personalBriefing';

/** Keep factual AI sentences verbatim; absent-comparison wording comes from fixed edition metadata. */
export function personalAiOverview(
  value: Extract<PersonalAiAnalysis, { status: 'available' }>,
  edition?: 'morning' | 'evening',
) {
  const missing = Object.values(value.draft.issues).every((i) =>
    Object.values(i.companies).every(
      (c) => c.previousChange.status === 'unavailable',
    ),
  );
  if (!missing)
    return { text: value.draft.overview.text, comparisonNote: null };
  const sentences = value.draft.overview.text.split(/(?<=[.!?。])\s+/);
  const text = sentences
    .filter((s) => !/비교 가능한|비교할 수 없|대비 변화는 평가할 수 없/.test(s))
    .join(' ');
  return {
    text,
    comparisonNote: `${edition === 'morning' ? '직전 퇴근 회차' : edition === 'evening' ? '당일 출근 회차' : '직전 회차'}의 같은 이슈·기업 판단이 없어 이전 대비 변화는 평가하지 않습니다.`,
  };
}
