import { sameBriefingInstant } from '@/util/briefingTime';
import type { BriefingResponse } from '@/types/briefing';
import {
  BODY,
  EMPTY,
  FOCUS_RING,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

/** D-BRF-01/02: saved summary only; a GET never creates a new judgment. */
export default function PriorityRoundSummary({
  result,
  compact,
}: {
  result: BriefingResponse;
  compact: boolean;
}) {
  const summary = result.prioritySummary;
  if (!summary) return null;
  if (
    summary.schemaVersion !== 'briefing-priority-summary-v1' ||
    summary.roundId !== result.id ||
    !sameBriefingInstant(summary.cutoff, result.dataAsOf) ||
    !summary.resultVersion ||
    !summary.text ||
    !Array.isArray(summary.evidenceIds) ||
    !summary.evidenceIds.length ||
    summary.evidenceIds.some(
      (id) => !result.references?.evidenceIds.includes(id),
    )
  )
    return (
      <p role="alert" className={EMPTY}>
        회차 요약의 근거·버전을 확인하지 못했습니다.
      </p>
    );
  const parts = summary.text.split('\n\n');
  return (
    <section className={SECTION} aria-label="새 버전 회차 요약">
      <h3 className={SECTION_TITLE}>
        {result.edition === 'morning'
          ? '오늘의 판단'
          : '오늘 평가와 다음 거래일'}
      </h3>
      <p className={`${BODY} whitespace-pre-line`}>
        {parts.slice(0, 2).join('\n\n')}
      </p>
      {parts.length > 2 && (
        <details className="mt-3" open={!compact}>
          <summary
            className={`cursor-pointer text-caption font-semibold ${FOCUS_RING}`}
          >
            판단 변화·전망·다음 확인사항
          </summary>
          <p className={`${BODY} mt-3 whitespace-pre-line`}>
            {parts.slice(2).join('\n\n')}
          </p>
        </details>
      )}
      {result.marketSummary && 'text' in result.marketSummary && (
        <details className="mt-3">
          <summary className={`cursor-pointer text-caption ${FOCUS_RING}`}>
            기존 요약 보관본
          </summary>
          <p className={`${BODY} mt-3 whitespace-pre-line`}>
            {result.marketSummary.text}
          </p>
        </details>
      )}
    </section>
  );
}
