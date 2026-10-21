import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import BriefingQuickRead from '@/components/briefing/BriefingQuickRead';
import type {
  BriefingMarketSummary,
  MarketOutlookAnalysis,
} from '@/types/briefing';

const cutoff = '2026-10-08T09:20:00+09:00';
const analysis: MarketOutlookAnalysis = {
  schemaVersion: 'zoop-market-outlook-analysis-v1',
  edition: 'morning',
  cutoff,
  mode: 'morning_update',
  previousPublication: {
    status: 'unavailable',
    kind: 'fixture',
    reason: 'immediate_previous_edition_missing',
  },
  coverage: {
    documents: 1,
    newDocuments: 1,
    backgroundDocuments: 0,
    companyNames: ['합성 기업'],
    marketRepresentative: false,
    sectorPriceFeedAvailable: false,
  },
  claims: [
    {
      claimId: 'f',
      kind: 'forecast',
      text: '수주가 확인되는 경우에만 상승 가능성을 본다. 확정된 전망이 아니다.',
      evidenceIds: [],
      indicatorIds: [],
      previousPublicationIds: [],
      previousForecastIds: [],
      evaluationIds: [],
      targetId: null,
      direction: 'up',
      conditions: ['실제 수주 확인'],
      counterFactors: ['공급 지연 가능성'],
      updateAction: null,
    },
  ],
  forecasts: [],
  forecastEvaluations: [],
  scopeNote: '합성 테스트',
};
const summary: BriefingMarketSummary = {
  text: '원래 전문',
  evidenceIds: [],
  generatedAt: cutoff,
  resultVersion: 'fixture',
  analysis,
};
describe('D-BRF-01·02 compact stored outlook', () => {
  it('keeps complete forecast wording and all conditions and counter factors', () => {
    render(
      <BriefingQuickRead
        result={{
          marketSummary: summary,
          edition: 'morning',
          dataAsOf: cutoff,
        }}
      />,
    );
    expect(screen.getByText(analysis.claims[0].text)).toBeTruthy();
    expect(screen.getByText('전망 조건: 실제 수주 확인')).toBeTruthy();
    expect(screen.getByText('반대 요인: 공급 지연 가능성')).toBeTruthy();
  });
  it('does not reuse an analysis from a different edition or cutoff', () => {
    render(
      <BriefingQuickRead
        result={{
          marketSummary: summary,
          edition: 'evening',
          dataAsOf: cutoff,
        }}
      />,
    );
    expect(screen.queryByText(analysis.claims[0].text)).toBeNull();
    expect(
      screen.getByText(
        '이 회차 기준과 일치하는 전망 분석을 표시할 수 없습니다.',
      ),
    ).toBeTruthy();
  });
});
