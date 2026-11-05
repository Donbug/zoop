import { expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import { withRoundMarket } from '@/util/briefingPersonalMarket';
import MarketIndicators from '@/components/briefing/MarketIndicators';
import type { BriefingResponse } from '@/types/briefing';

function common(): BriefingResponse {
  return {
    id: 'round',
    date: '2026-11-02',
    edition: 'evening',
    status: 'published',
    scheduledAt: '2026-11-02T17:30:00+09:00',
    dataAsOf: '2026-11-02T08:30:00Z',
    publishedAt: '2026-11-02T08:32:00Z',
    generatedAt: '2026-11-02T08:31:00Z',
    graphVersion: 'synthetic',
    marketSummary: { status: 'unavailable', reason: '합성 검증' },
    sinceMorning: null,
    emptyReason: null,
    notice: null,
    metadata: {
      source: 'synthetic',
      asOf: '2026-11-02T08:30:00Z',
      graphVersion: 'synthetic',
      requestId: 'synthetic',
      partial: false,
      failures: [],
    },
    corrections: [],
    items: [],
    marketVariables: {
      status: 'available',
      referenceAt: '2026-11-02T08:30:00Z',
      collectedAt: '2026-11-02T08:29:00Z',
      indicators: [
        {
          id: 'kospi',
          label: 'KOSPI',
          unit: 'pt',
          status: 'ok',
          value: 2500,
          valueKind: 'close',
          observedDate: '2026-11-02',
          observedAt: null,
          baseline: { value: 2490, date: '2026-10-30', at: null },
          change: 10,
          changeRate: 10 / 2490,
          reason: null,
          source: null,
        },
      ],
    },
  };
}
function personal(): BriefingResponse {
  return {
    ...common(),
    marketVariables: { status: 'unavailable', reason: '저장 지표 없음' },
  };
}
test('saved same-round common indicators appear in personal view without mutating either publication', () => {
  const pub = common(),
    own = personal();
  const before = JSON.stringify([pub, own]);
  const projected = withRoundMarket(own, pub);
  render(<MarketIndicators variables={projected.marketVariables} compact />);
  expect(screen.getByText('2,500 pt')).not.toBeNull();
  expect(screen.getByText('2026-11-02 종가')).not.toBeNull();
  expect(JSON.stringify([pub, own])).toBe(before);
});
test('an existing personal snapshot is never replaced', () => {
  const own = common(),
    pub = common();
  expect(withRoundMarket(own, pub)).toBe(own);
});
test('another round, slot, cutoff, correction or unavailable common result cannot supply prices', () => {
  for (const mutate of [
    (r: BriefingResponse) => {
      r.id = 'other';
    },
    (r: BriefingResponse) => {
      r.date = '2026-11-03';
    },
    (r: BriefingResponse) => {
      r.edition = 'morning';
    },
    (r: BriefingResponse) => {
      r.status = 'suspended';
    },
    (r: BriefingResponse) => {
      r.publishedAt = null;
    },
    (r: BriefingResponse) => {
      r.dataAsOf = '2026-11-03T08:30:00Z';
    },
    (r: BriefingResponse) => {
      r.scheduledAt = '2026-11-03T08:30:00Z';
    },
    (r: BriefingResponse) => {
      if (r.marketVariables.status === 'available')
        r.marketVariables.referenceAt = '2026-11-03T08:30:00Z';
    },
    (r: BriefingResponse) => {
      r.corrections = [{} as BriefingResponse['corrections'][number]];
    },
  ]) {
    const own = personal(),
      pub = common();
    mutate(pub);
    expect(withRoundMarket(own, pub)).toBe(own);
  }
});
test('late historical collection remains visibly distinct from an on-time snapshot even in compact mode', () => {
  const pub = common();
  if (pub.marketVariables.status === 'available')
    pub.marketVariables.collectedAt = '2026-11-04T08:29:00Z';
  render(
    <MarketIndicators
      variables={withRoundMarket(personal(), pub).marketVariables}
      compact
    />,
  );
  expect(screen.getByText(/사후 조회한 일별 값/)).not.toBeNull();
  expect(screen.getByText('2026-11-02 종가')).not.toBeNull();
});
