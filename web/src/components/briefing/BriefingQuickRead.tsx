import type { BriefingResponse } from '@/types/briefing';
import { matchingBriefingAnalysis } from './briefingAnalysis';
import {
  BODY,
  EMPTY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

const directions = {
  up: '상승 가능성',
  down: '하락 가능성',
  flat: '보합 가능성',
  uncertain: '불확실',
};
const updates = {
  maintain: '유지',
  strengthen: '강화',
  weaken: '완화',
  withdraw: '철회',
};

/** 저장된 검증 문장을 발췌한다. 재작성·문장 자르기·새 AI 호출을 하지 않는다. */
export default function BriefingQuickRead({
  result,
}: {
  result: Pick<BriefingResponse, 'marketSummary' | 'edition' | 'dataAsOf'>;
}) {
  const analysis = matchingBriefingAnalysis(
    result.marketSummary,
    result.edition,
    result.dataAsOf,
  );
  const forecast = analysis?.claims.find((claim) => claim.kind === 'forecast');
  const change = analysis?.claims.find(
    (claim) =>
      claim.kind ===
      (result.edition === 'morning' ? 'forecast_update' : 'result_comparison'),
  );
  const fact = analysis?.claims.find((claim) => claim.kind === 'fact');
  return (
    <section className={SECTION} aria-labelledby="briefing-quick-title">
      <p className={NOTE}>핵심 먼저 읽기 · 발행 시 저장한 문장</p>
      <h3
        id="briefing-quick-title"
        className="mt-2 mb-3 text-title leading-snug font-bold tracking-tight"
      >
        {result.edition === 'morning' ? '오늘의 전망' : '다음 거래일의 전망'}
        {forecast?.direction && (
          <span className="ml-2 text-zoop-muted">
            · {directions[forecast.direction]}
          </span>
        )}
      </h3>
      {analysis ? (
        <>
          {fact && <p className={`${BODY} mb-3`}>{fact.text}</p>}
          {forecast ? (
            <>
              <p className={`${BODY} font-semibold`}>{forecast.text}</p>
              {forecast.conditions.length > 0 && (
                <p className={`${NOTE} mt-2`}>
                  전망 조건: {forecast.conditions.join(' · ')}
                </p>
              )}
              {forecast.counterFactors.length > 0 && (
                <p className={`${NOTE} mt-2`}>
                  반대 요인: {forecast.counterFactors.join(' · ')}
                </p>
              )}
            </>
          ) : (
            <p className={NOTE}>
              검증된 새 전망이 없습니다. 기존 시장 요약과 핵심 이슈를 확인해
              주세요.
            </p>
          )}
          {change && (
            <details className="mt-4 rounded-panel border border-panel-line bg-zoop-wash p-3">
              <summary
                className={`min-h-11 cursor-pointer content-center text-body font-semibold ${FOCUS_RING}`}
              >
                {result.edition === 'morning'
                  ? '이전 전망 대비 변화'
                  : '아침 예상과 실제 결과 비교'}
                {change.updateAction
                  ? ` · ${updates[change.updateAction]}`
                  : ' · 판단 근거 보기'}
              </summary>
              <p className={`${BODY} mt-2`}>{change.text}</p>
              {change.conditions.length > 0 && (
                <p className={NOTE}>
                  비교 조건: {change.conditions.join(' · ')}
                </p>
              )}
              {change.counterFactors.length > 0 && (
                <p className={NOTE}>
                  반대 요인: {change.counterFactors.join(' · ')}
                </p>
              )}
            </details>
          )}
        </>
      ) : (
        <div>
          <h4 className={SECTION_TITLE}>시장 요약</h4>
          <p className={EMPTY}>
            {'text' in result.marketSummary
              ? result.marketSummary.analysis
                ? '이 회차 기준과 일치하는 전망 분석을 표시할 수 없습니다.'
                : result.marketSummary.text
              : result.marketSummary.reason}
          </p>
        </div>
      )}
    </section>
  );
}
