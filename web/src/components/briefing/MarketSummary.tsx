import { Link } from 'react-router-dom';
import type { BriefingEdition, BriefingMarketSummary } from '@/types/briefing';
import type {
  MarketOutlookAnalysis,
  MarketOutlookClaim,
  MarketOutlookTarget,
} from '@/types/briefing/marketOutlook';
import { briefingTime } from '@/util/briefingTime';
import {
  BODY,
  EMPTY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

const labels = { kospi: 'KOSPI', kosdaq: 'KOSDAQ' };
const updateLabels = {
  maintain: '유지',
  strengthen: '강화',
  weaken: '완화',
  withdraw: '철회',
};
const unavailableReasons: Record<string, string> = {
  condition_outcomes_not_observed:
    '전망에 붙인 조건의 충족 여부를 관측하지 못해 평가할 수 없습니다.',
  direction_not_testable:
    '이전 전망의 방향이 불확실로 기록되어 방향 일치 여부를 평가하지 않습니다.',
  target_period_not_finished:
    '전망 대상 거래일의 장이 아직 끝나지 않아 결과를 평가할 수 없습니다.',
  exact_target_observation_missing:
    '전망 대상 거래일과 일치하는 종가가 없어 평가할 수 없습니다.',
  immediate_previous_edition_missing:
    '직전 회차의 시장 분석이 없어 이전 전망을 비교하지 않습니다.',
  immediate_previous_summary_withheld:
    '직전 회차에 비교 가능한 검증된 시장 분석이 없어 사용하지 않습니다.',
};
const number = (value: number) =>
  value.toLocaleString('ko-KR', { maximumFractionDigits: 2 });

function TargetBasis({ target }: { target: MarketOutlookTarget }) {
  return (
    <p className={NOTE}>
      대상 {target.targetDate} {labels[target.indicatorId]} 종가 · 비교 기준{' '}
      {target.baselineDate} {number(target.baselineValue)} pt
    </p>
  );
}

function Claim({
  claim,
  analysis,
}: {
  claim: MarketOutlookClaim;
  analysis: MarketOutlookAnalysis;
}) {
  const forecast = analysis.forecasts.find(
    (entry) => entry.target.targetId === claim.targetId,
  );
  return (
    <li className="flex flex-col gap-1.5">
      {claim.updateAction && (
        <p className={`${NOTE} font-semibold`}>
          이전 전망 {updateLabels[claim.updateAction]}
        </p>
      )}
      <p className={BODY}>{claim.text}</p>
      {forecast && <TargetBasis target={forecast.target} />}
      {claim.conditions.length > 0 && (
        <p className={NOTE}>전망 조건: {claim.conditions.join(' · ')}</p>
      )}
      {claim.counterFactors.length > 0 && (
        <p className={NOTE}>반대 요인: {claim.counterFactors.join(' · ')}</p>
      )}
    </li>
  );
}

/** D-BRF-01·02: 발행 시 검증한 문장·전망·평가만 분류한다. 화면에서 새 전망을 만들지 않는다. */
export default function MarketSummary({
  summary,
  edition,
  dataAsOf,
}: {
  summary: BriefingMarketSummary;
  edition: BriefingEdition;
  dataAsOf: string | null;
}) {
  const stored = 'text' in summary ? summary.analysis : undefined;
  const expectedMode =
    edition === 'morning' ? 'morning_update' : 'evening_review';
  const analysis =
    stored?.schemaVersion === 'zoop-market-outlook-analysis-v1' &&
    stored.edition === edition &&
    stored.mode === expectedMode &&
    dataAsOf !== null &&
    Date.parse(stored.cutoff) === Date.parse(dataAsOf)
      ? stored
      : undefined;
  const previous = analysis?.previousPublication;
  const groups: { kind: MarketOutlookClaim['kind']; title: string }[] = [
    { kind: 'fact', title: '확인된 정보' },
    { kind: 'interpretation', title: '시장에 대한 해석' },
    { kind: 'forecast_update', title: '이전 전망에서 달라진 점' },
    { kind: 'result_comparison', title: '아침 예상과 관측 결과 비교' },
    {
      kind: 'forecast',
      title:
        edition === 'morning'
          ? '오늘의 조건부 전망'
          : '다음 거래일의 조건부 전망',
    },
  ];
  return (
    <section className={SECTION} aria-labelledby="market-summary-title">
      <h3 id="market-summary-title" className={SECTION_TITLE}>
        시장 요약
      </h3>
      {!analysis ? (
        stored ? (
          <p className={EMPTY}>
            이 회차 기준과 일치하는 전망 분석을 표시할 수 없습니다.
          </p>
        ) : (
          <p className={BODY}>
            {'text' in summary ? summary.text : summary.reason}
          </p>
        )
      ) : (
        <div className="flex flex-col gap-5">
          <div>
            <p className="mb-2 text-[13px] font-semibold">
              {edition === 'morning'
                ? '오늘 전망 갱신'
                : '아침 예상 점검 · 다음 거래일 전망'}
            </p>
            <p className={NOTE}>분석 기준 {briefingTime(analysis.cutoff)}</p>
            <p className={NOTE}>
              확인된 기업 {analysis.coverage.companyNames.length}곳 · 자료{' '}
              {analysis.coverage.documents}건 (새 자료{' '}
              {analysis.coverage.newDocuments}건 · 배경 자료{' '}
              {analysis.coverage.backgroundDocuments}건)
            </p>
            {analysis.coverage.companyNames.length > 0 && (
              <details className="mt-2">
                <summary
                  className={`cursor-pointer text-[11px] text-zoop-muted ${FOCUS_RING}`}
                >
                  분석에 포함한 기업
                </summary>
                <p className={`${NOTE} mt-1`}>
                  {analysis.coverage.companyNames.join(' · ')}
                </p>
              </details>
            )}
            {previous?.status === 'available' ? (
              <p className={`${NOTE} mt-2`}>
                비교 브리핑{' '}
                {previous.date && previous.edition ? (
                  <Link
                    className={`underline underline-offset-4 ${FOCUS_RING}`}
                    to={`/briefing?date=${encodeURIComponent(previous.date)}&edition=${previous.edition}`}
                  >
                    {previous.date}{' '}
                    {previous.edition === 'morning' ? '출근' : '퇴근'}
                  </Link>
                ) : (
                  previous.roundId
                )}
                {previous.cutoff &&
                  ` · 데이터 기준 ${briefingTime(previous.cutoff)}`}
              </p>
            ) : (
              <p className={`${EMPTY} mt-2`}>
                {unavailableReasons[previous?.reason ?? ''] ??
                  '직전 회차의 검증된 전망이 없어 이전 전망을 비교하지 않습니다.'}
              </p>
            )}
          </div>
          {groups.map((group) => {
            const claims = analysis.claims.filter(
              (claim) => claim.kind === group.kind,
            );
            return claims.length > 0 ? (
              <div key={group.kind}>
                <h4 className={SECTION_TITLE}>{group.title}</h4>
                <ul className="flex flex-col gap-3">
                  {claims.map((claim) => (
                    <Claim
                      key={claim.claimId}
                      claim={claim}
                      analysis={analysis}
                    />
                  ))}
                </ul>
              </div>
            ) : null;
          })}
          {!analysis.claims.some((claim) => claim.kind === 'forecast') && (
            <p className={NOTE}>
              이 회차에는 검증을 통과한 새로운 조건부 전망이 없습니다.
            </p>
          )}
          <div>
            <h4 className={SECTION_TITLE}>이전 전망의 관측·평가</h4>
            {analysis.forecastEvaluations.length === 0 ? (
              <p className={NOTE}>
                비교할 수 있는 구조화된 이전 전망이 없습니다.
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {analysis.forecastEvaluations.map((evaluation) => (
                  <li
                    key={evaluation.evaluationId}
                    className="rounded-[3px] bg-zoop-wash p-3"
                  >
                    <TargetBasis target={evaluation.target} />
                    {evaluation.status === 'evaluated' &&
                    evaluation.actualValue !== null &&
                    evaluation.directionMatched !== null ? (
                      <p className={`${NOTE} mt-1`}>
                        관측 종가 {number(evaluation.actualValue)} pt · 기준값
                        대비 방향{' '}
                        {evaluation.directionMatched ? '일치' : '불일치'}
                      </p>
                    ) : (
                      <p className={`${NOTE} mt-1`}>
                        평가 불가 ·{' '}
                        {unavailableReasons[evaluation.reason ?? ''] ??
                          '정확한 비교에 필요한 관측 자료가 없습니다.'}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <p className={NOTE}>{analysis.scopeNote}</p>
        </div>
      )}
    </section>
  );
}
