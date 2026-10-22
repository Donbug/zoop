import type { BriefingEdition, BriefingMarketSummary } from '@/types/briefing';

/** 간단히/전체 보기가 같은 회차 검증을 사용한다. 불일치 분석은 요약에도 노출하지 않는다. */
export function matchingBriefingAnalysis(
  summary: BriefingMarketSummary,
  edition: BriefingEdition,
  dataAsOf: string | null,
) {
  const stored = 'text' in summary ? summary.analysis : undefined;
  return stored?.schemaVersion === 'zoop-market-outlook-analysis-v1' &&
    stored.edition === edition &&
    stored.mode ===
      (edition === 'morning' ? 'morning_update' : 'evening_review') &&
    dataAsOf !== null &&
    Date.parse(stored.cutoff) === Date.parse(dataAsOf)
    ? stored
    : undefined;
}
