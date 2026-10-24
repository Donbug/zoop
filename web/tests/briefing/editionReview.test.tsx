import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import EditionReview from '@/components/briefing/EditionReview';
import {
  businessResult,
  marketCoverage,
  validEditionReview,
} from '@/util/editionReview';
import type { BriefingResponse } from '@/types/briefing';
import type {
  EditionCompanyCopy,
  EditionCompanyReview,
  EditionReview as Review,
} from '@/types/briefing/editionReview';
const s = (text: string, id?: string) => ({
  text,
  evidenceIds: id ? [id] : [],
});
function fixture(): BriefingResponse {
  const previous: EditionCompanyCopy = {
    companyId: 'A',
    stance: 'watch',
    title: s('아침 제목', 'a'),
    takeaway: s('실제 납품을 확인합니다.', 'a'),
    newInformation: s('계획입니다.', 'a'),
    judgment: s('실제 아침 판단입니다.', 'a'),
    watch: [s('실제 납품 확인', 'a')],
    positive: s('납품 시 강화', 'a'),
    negative: s('취소 시 약화', 'a'),
    checks: [],
  };
  const companies: EditionCompanyReview[] = ['B', 'A'].map((id, i) => ({
    ...previous,
    companyId: id,
    companyName: i ? '아침기업' : '새기업',
    role: i ? 'tracked' : 'selected',
    sourceIds: [id.toLowerCase()],
    previous: i ? previous : null,
    title: s(i ? '아침 조건 추적' : '새 핵심 기업', id.toLowerCase()),
    takeaway: s('계획의 실행을 봅니다.', id.toLowerCase()),
    newInformation: s('새 자료의 확인 범위', id.toLowerCase()),
    judgment: s('현재 판단', id.toLowerCase()),
    watch: [s('실제 납품 확인', id.toLowerCase())],
    positive: s('실제 납품 시 강화', id.toLowerCase()),
    negative: s('취소 시 약화', id.toLowerCase()),
    checks: i
      ? [
          {
            condition: '실제 납품 확인',
            status: 'not_observed',
            observation: s('새 근거가 관측되지 않았습니다.', 'a'),
          },
        ]
      : [],
    price: {
      companyId: id,
      cutoff: '2026-10-22T17:30:00+09:00',
      currency: 'USD',
      exchangeTimezone: 'America/New_York',
      source: '합성 시험',
      official: false,
      note: '합성 시세',
      status: 'available',
      reason: null,
      latest: {
        value: '110',
        observedAt: '2026-10-22T05:00:00Z',
        sessionDate: '2026-10-22',
        kind: 'daily_close',
      },
      baseline: {
        value: '100',
        observedAt: '2026-10-22T00:20:00Z',
        sessionDate: '2026-10-22',
        kind: 'five_minute_close',
      },
      baselineKind: 'morning_cutoff',
      comparisonStatus: 'available',
      change: '10',
      changeRate: '10.00',
      sources: [],
    },
  }));
  const r: Review = {
    schemaVersion: 'zoop-edition-review-v1',
    status: 'REVIEWED',
    verificationMode: 'editorial_source_review',
    reviewer: 'codex',
    reviewedAt: '2026-10-24T02:00:00Z',
    resultVersion: 'edition-new',
    roundId: 'r',
    date: '2026-10-22',
    edition: 'evening',
    cutoff: '2026-10-22T17:30:00+09:00',
    analysisVersion: 'current',
    scopeNote: '합성 검토',
    previousReview: {
      roundId: 'am',
      resultVersion: 'am-v',
      date: '2026-10-22',
      edition: 'morning',
      cutoff: '2026-10-22T09:20:00+09:00',
      draft: { companies: [previous] },
    },
    sources: Object.fromEntries(
      ['a', 'b'].map((id) => [
        id,
        {
          title: '합성 원문',
          url: 'https://example.com/' + id,
          publishedAt: '2026-10-21T17:00:00+09:00',
          quote: '계획입니다.',
          fullBody: '조건부 계획입니다.',
        },
      ]),
    ),
    marketVariables: {
      status: 'available',
      indicators: ['kospi', 'kosdaq'].map((id) => ({
        id: id as 'kospi' | 'kosdaq',
        label: id,
        status: 'ok',
        value: 100,
        unit: 'pt',
        valueKind: 'close',
        observedDate: '2026-10-22',
        observedAt: null,
        baseline: { date: '2026-10-20', at: null, value: 110 },
        change: -10,
        changeRate: -0.09,
        reason: null,
        reasonCode: null,
        source: {
          name: '합성 시세',
          url: 'https://example.com/market',
          official: false,
          delayNote: null,
        },
      })),
    },
    capabilities: {
      intraday: 'unavailable',
      sectors: 'unavailable',
      flows: 'unavailable',
      calendar: 'unverified',
    },
    headline: '오늘의 결과와 아침 조건을 구분합니다',
    summary: s('오늘 요약'),
    marketInterpretation: s('중간 기준이 빠져 하루 방향은 판단하지 않습니다.'),
    comparison: s('아침 조건을 다시 점검합니다.'),
    nextSession: s('다음 거래일 확인 조건입니다.'),
    companies,
  };
  return {
    id: 'r',
    date: r.date,
    edition: 'evening',
    dataAsOf: r.cutoff,
    items: [{ companies: [{ id: 'B' }] }],
    companyOutlooks: { resultVersion: 'current' },
    editionReview: r,
  } as unknown as BriefingResponse;
}
describe('D-BRF-01/02 edition reviews', () => {
  it('separates price gains from evidence confirmation and keeps every morning company', async () => {
    const r = fixture();
    expect(validEditionReview(r)).toBeTruthy();
    expect(businessResult(r.editionReview!.companies[1])).toBe(
      '조건 미관측 · 평가 유보',
    );
    render(<EditionReview result={r} compact />);
    expect(screen.getByText('아침 기업 판단 점검')).toBeTruthy();
    expect(screen.getByText('다음 거래일 전망·확인 조건')).toBeTruthy();
    const c = screen.getByLabelText('아침기업 하루 점검');
    await userEvent.click(c.querySelector('summary')!);
    expect(c.hasAttribute('open')).toBe(true);
    expect(screen.getByText('실제 아침 판단입니다.')).toBeTruthy();
  });
  it('does not treat a two-day comparison or stale close as today performance', () => {
    const r = fixture().editionReview!;
    expect(marketCoverage(r).todayClose).toBe(true);
    expect(marketCoverage(r).dailyComparable).toBe(false);
    if (r.marketVariables.status === 'available')
      r.marketVariables.indicators.forEach((i) => {
        i.observedDate = '2026-10-20';
      });
    expect(marketCoverage(r).todayClose).toBe(false);
  });
  it('rejects missing morning members, rewritten conditions and confirmations based on older news', () => {
    for (const kind of ['missing', 'rewrite', 'confirmation', 'drop_watch']) {
      const r = fixture();
      const u = r.editionReview!;
      if (kind === 'missing') u.companies.pop();
      if (kind === 'drop_watch')
        u.companies[1].watch = [s('다른 관찰 과제', 'a')];
      if (kind === 'rewrite')
        u.companies[1].checks[0].condition = '변경한 조건';
      if (kind === 'confirmation')
        u.companies[1].checks[0].status = 'confirmed';
      expect(validEditionReview(r)).toBeNull();
    }
  });
  it('uses a distinct morning focus and a visible missing-morning state', () => {
    const r = fixture();
    r.edition = 'morning';
    r.editionReview!.edition = 'morning';
    r.editionReview!.previousReview = null;
    r.editionReview!.companies = r.editionReview!.companies.slice(0, 1);
    render(<EditionReview result={r} compact />);
    expect(screen.getByText('오늘 어디에 집중할까요?')).toBeTruthy();
    expect(screen.getByText('오늘 확인할 사건·판단 변경 조건')).toBeTruthy();
  });
});
