import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import MarketSummary from '@/components/briefing/MarketSummary';
import type { BriefingEdition, MarketOutlookAnalysis } from '@/types/briefing';
import type {
  MarketOutlookClaim,
  MarketOutlookTarget,
} from '@/types/briefing/marketOutlook';

// D-BRF-01·02: 합성 전망. 실제 지표·기업·적중 실적으로 사용하지 않는다.
const target: MarketOutlookTarget = {
  targetId: 'fixture-target',
  indicatorId: 'kospi',
  valueKind: 'close',
  baselineDate: '2026-10-06',
  baselineValue: 2600,
  targetDate: '2026-10-07',
  targetEnd: '2026-10-07T15:30:00+09:00',
  calendarRef: 'fixture-calendar',
  rule: 'close_vs_baseline_v1',
};
function claim(
  kind: MarketOutlookClaim['kind'],
  text: string,
  overrides: Partial<MarketOutlookClaim> = {},
): MarketOutlookClaim {
  return {
    claimId: `fixture-${kind}`,
    kind,
    text,
    evidenceIds: ['fixture-evidence'],
    indicatorIds: [],
    previousPublicationIds: [],
    previousForecastIds: [],
    evaluationIds: [],
    targetId: null,
    direction: null,
    conditions: [],
    counterFactors: [],
    updateAction: null,
    ...overrides,
  };
}
function analysis(edition: BriefingEdition = 'morning'): MarketOutlookAnalysis {
  const cutoff =
    edition === 'morning'
      ? '2026-10-07T09:20:00+09:00'
      : '2026-10-07T17:30:00+09:00';
  return {
    schemaVersion: 'zoop-market-outlook-analysis-v1',
    edition,
    cutoff,
    mode: edition === 'morning' ? 'morning_update' : 'evening_review',
    previousPublication: {
      status: 'available',
      kind: 'simulated_previous_output',
      roundId: 'fixture-prior',
      date: edition === 'morning' ? '2026-10-06' : '2026-10-07',
      edition: edition === 'morning' ? 'evening' : 'morning',
      cutoff:
        edition === 'morning'
          ? '2026-10-06T17:30:00+09:00'
          : '2026-10-07T09:20:00+09:00',
      resultVersion: 'fixture-version',
    },
    coverage: {
      documents: 10,
      newDocuments: 2,
      backgroundDocuments: 8,
      companyNames: ['합성 기업 갑', '합성 기업 을'],
      marketRepresentative: false,
      sectorPriceFeedAvailable: false,
    },
    claims: [
      claim('fact', '합성 회사가 공급계약 계획을 공시했다.'),
      claim(
        'interpretation',
        '확인된 계약 계획은 해당 기업의 수주 기대를 뒷받침할 수 있다.',
      ),
      claim('forecast', '조건이 충족되면 지수 상승 가능성을 살펴본다.', {
        targetId: target.targetId,
        direction: 'up',
        conditions: ['수주 증가가 실제로 확인될 경우'],
        counterFactors: ['공급 지연 가능성'],
      }),
      edition === 'morning'
        ? claim(
            'forecast_update',
            '새 정보를 반영해 이전 상승 전망을 완화한다.',
            {
              previousForecastIds: ['fixture-prior-forecast'],
              updateAction: 'weaken',
            },
          )
        : claim(
            'result_comparison',
            '아침 예상과 종가 관측을 비교하되 계약이 상승 원인이라고 단정하지 않는다.',
            { previousPublicationIds: ['fixture-prior'] },
          ),
    ],
    forecasts: [
      {
        forecastId: 'fixture-forecast',
        target,
        text: '조건부 상승 전망',
        direction: 'up',
        conditions: ['수주 증가가 실제로 확인될 경우'],
        counterFactors: ['공급 지연 가능성'],
        evidenceIds: ['fixture-evidence'],
        indicatorIds: ['kospi'],
      },
    ],
    forecastEvaluations: [
      {
        evaluationId: 'fixture-evaluation',
        forecastId: 'fixture-prior-forecast',
        target,
        rule: 'close_vs_baseline_v1',
        status: 'unavailable',
        reason: 'target_period_not_finished',
        actualValue: null,
        actualDirection: null,
        directionMatched: null,
      },
    ],
    scopeNote:
      '확인된 기업 자료만 분석했으며 업종 시세와 시장 전체 대표성은 확인하지 않았습니다.',
  };
}
function show(
  value: MarketOutlookAnalysis,
  edition = value.edition,
  dataAsOf: string | null = value.cutoff,
) {
  return render(
    <MemoryRouter>
      <MarketSummary
        summary={{
          text: '기존 요약 문안',
          generatedAt: '2026-10-20T10:00:00+09:00',
          resultVersion: 'fixture',
          evidenceIds: ['fixture-evidence'],
          analysis: value,
        }}
        edition={edition}
        dataAsOf={dataAsOf}
      />
    </MemoryRouter>,
  );
}
describe('D-BRF-01·02 저장된 전망형 시장 분석', () => {
  it('출근 분석에서 전체 기업 범위·이전 회차·해석·갱신과 조건부 전망을 구분한다', () => {
    show(analysis());
    expect(screen.getByText('오늘 전망 갱신')).toBeTruthy();
    expect(screen.getByText(/확인된 기업 2곳 · 자료 10건/)).toBeTruthy();
    expect(screen.getByText('합성 기업 갑 · 합성 기업 을')).toBeTruthy();
    expect(
      screen
        .getByRole('link', { name: '2026-10-06 퇴근' })
        .getAttribute('href'),
    ).toBe('/briefing?date=2026-10-06&edition=evening');
    expect(screen.getByRole('heading', { name: '확인된 정보' })).toBeTruthy();
    expect(
      screen.getByRole('heading', { name: '시장에 대한 해석' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('heading', { name: '오늘의 전망' }),
    ).toBeTruthy();
    expect(screen.getByText('이전 전망 완화')).toBeTruthy();
    expect(
      screen.getByText(/전망 조건: 수주 증가가 실제로 확인될 경우/),
    ).toBeTruthy();
    expect(screen.getByText(/반대 요인: 공급 지연 가능성/)).toBeTruthy();
    expect(screen.queryByText('기존 요약 문안')).toBeNull();
  });
  it.each([
    ['condition_outcomes_not_observed', '조건의 충족 여부를 관측하지 못해'],
    ['target_period_not_finished', '장이 아직 끝나지 않아'],
    ['exact_target_observation_missing', '일치하는 종가가 없어'],
  ])(
    '평가 불가 사유 %s를 설명하고 방향 일치를 만들지 않는다',
    (reason, text) => {
      const value = analysis();
      value.forecastEvaluations[0].reason = reason;
      show(value);
      expect(screen.getByText(new RegExp(text))).toBeTruthy();
      expect(screen.queryByText(/방향 일치/)).toBeNull();
      expect(screen.queryByText(/적중률/)).toBeNull();
    },
  );
  it('퇴근 분석은 저장된 아침 비교와 다음 거래일 전망을 표시한다', () => {
    const value = analysis('evening');
    value.forecastEvaluations[0] = {
      ...value.forecastEvaluations[0],
      status: 'evaluated',
      reason: null,
      actualValue: 2610,
      actualDirection: 'up',
      directionMatched: true,
    };
    value.forecasts[0].target = {
      ...target,
      targetDate: '2026-10-08',
      targetEnd: '2026-10-08T15:30:00+09:00',
    };
    show(value);
    expect(
      screen.getByRole('heading', { name: '아침 예상과 관측 결과 비교' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('heading', { name: '다음 거래일의 전망' }),
    ).toBeTruthy();
    expect(screen.getByText(/대상 2026-10-08 KOSPI 종가/)).toBeTruthy();
    expect(
      screen.getByText(/관측 종가 2,610 pt · 기준값 대비 방향 일치/),
    ).toBeTruthy();
  });
  it('이전 회차가 보류됐으면 비교와 새 전망을 만들어 채우지 않는다', () => {
    const value = analysis();
    value.previousPublication = {
      status: 'unavailable',
      kind: 'simulated_previous_output',
      reason: 'immediate_previous_summary_withheld',
    };
    value.claims = value.claims.filter((entry) => entry.kind === 'fact');
    value.forecasts = [];
    value.forecastEvaluations = [];
    show(value);
    expect(
      screen.getByText(/비교 가능한 검증된 시장 분석이 없어 사용하지 않습니다/),
    ).toBeTruthy();
    expect(
      screen.getByText(
        '이 회차에는 검증을 통과한 새로운 전망이 없습니다.',
      ),
    ).toBeTruthy();
    expect(
      screen.queryByRole('heading', { name: '오늘의 전망' }),
    ).toBeNull();
  });
  it('다른 회차의 구조화 분석을 현재 회차 전망으로 노출하지 않는다', () => {
    show(analysis(), 'evening', '2026-10-07T17:30:00+09:00');
    expect(screen.queryByText('기존 요약 문안')).toBeNull();
    expect(
      screen.getByText(
        '이 회차 기준과 일치하는 전망 분석을 표시할 수 없습니다.',
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText('조건이 충족되면 지수 상승 가능성을 살펴본다.'),
    ).toBeNull();
  });
  it('analysis가 없는 과거 응답과 미제공 사유를 그대로 유지한다', () => {
    const { rerender } = render(
      <MarketSummary
        summary={{ status: 'unavailable', reason: '저장된 시장 요약 없음' }}
        edition="morning"
        dataAsOf={null}
      />,
    );
    expect(screen.getByText('저장된 시장 요약 없음')).toBeTruthy();
    rerender(
      <MarketSummary
        summary={{
          text: '기존 요약 유지',
          evidenceIds: [],
          generatedAt: 'fixture',
          resultVersion: 'fixture',
        }}
        edition="morning"
        dataAsOf={null}
      />,
    );
    expect(screen.getByText('기존 요약 유지')).toBeTruthy();
  });
});
