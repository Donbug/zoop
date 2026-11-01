import { validAiPriceOutlooks } from '@/util/aiPriceOutlook';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import CompanyPriceContext, {
  PriceMarketReference,
} from '@/components/briefing/CompanyPriceContext';
import { validPriceContext } from '@/util/briefingPriceContext';
import type { BriefingResponse } from '@/types/briefing';
import type {
  BriefingPriceContext,
  CompanyPriceContext as Context,
} from '@/types/briefing/priceContext';

const cutoff = '2026-10-22T08:30:00Z';
function company(): Context {
  return {
    companyId: 'NASDAQ:META',
    companyName: '합성 Meta',
    currency: 'USD',
    provider: 'toss',
    cutoff,
    responseSha256s: ['a'.repeat(64), 'b'.repeat(64)],
    status: 'available',
    sessionDate: '2026-10-21',
    exchangeTimezone: 'America/New_York',
    completeSession: true,
    barCount: 78,
    latest: {
      value: '102',
      observedAt: '2026-10-21T20:00:00Z',
      kind: 'daily_close',
    },
    day: {
      baselineDate: '2026-10-20',
      baselineClose: '100',
      changeRatePercent: '2.00',
      kind: 'provider_daily_bar',
      open: '100',
      high: '110',
      low: '99',
      closeOrLast: '102',
      volume: '1000',
      from: '2026-10-21T13:30:00Z',
      to: '2026-10-21T20:00:00Z',
    },
    summary: '제공 종가는 102 USD입니다.',
    flow: '고점보다 낮게 마감했습니다.',
    news: [
      {
        evidenceId: 's1',
        publishedAt: '2026-10-21T20:01:00Z',
        timing: 'after_session',
        status: 'no_post_news_trade',
        postNewsBars: 0,
        before: null,
        changeRatePercent: null,
        observation:
          '기사 공개 후 완료 봉이 없어 기사 반응을 평가하지 않습니다.',
      },
    ],
    sinceMorning: {
      status: 'no_new_session',
      observation: '출근 이후 새 정규장 관측이 없습니다.',
    },
    interpretation: '사업 조건 확인과 가격 움직임은 구분합니다.',
    limitation: '인과관계·예측 적중을 입증하지 않습니다.',
  };
}
function result(): BriefingResponse {
  const context: BriefingPriceContext = {
    schemaVersion: 'zoop-company-price-context-v1',
    status: 'derived',
    authorship: 'deterministic_price_observation',
    roundId: 'r',
    date: '2026-10-22',
    edition: 'evening',
    cutoff,
    reviewVersion: 'v1',
    resultVersion: 'price-v1',
    generatedAt: '2026-10-24T00:00:00Z',
    scopeNote: '합성 시험',
    companies: [company()],
  };
  return {
    id: 'r',
    companyPriceContext: context,
    editionReview: {
      roundId: 'r',
      date: context.date,
      edition: context.edition,
      cutoff,
      resultVersion: 'v1',
      companies: [
        { companyId: 'NASDAQ:META', newInformation: { evidenceIds: ['s1'] } },
      ],
      sources: { s1: { publishedAt: '2026-10-21T20:01:00Z' } },
    },
  } as unknown as BriefingResponse;
}
afterEach(cleanup);
describe('cutoff-bound company price observations', () => {
  it('shows after-close news and no new US session without implying prediction success', () => {
    render(<CompanyPriceContext context={company()} evening />);
    expect(screen.getByText('제공 종가는 102 USD입니다.')).toBeTruthy();
    expect(
      screen.getByText('출근 이후 새 정규장 관측이 없습니다.'),
    ).toBeTruthy();
    expect(screen.getByText(/기사 공개 후 완료 봉이 없어/)).toBeTruthy();
    expect(
      screen.getByText('사업 조건 확인과 가격 움직임은 구분합니다.'),
    ).toBeTruthy();
    expect(
      screen.getByText('인과관계·예측 적중을 입증하지 않습니다.'),
    ).toBeTruthy();
  });
  it('requires the original review version and company ownership', () => {
    const r = result();
    expect(validPriceContext(r)).toBeTruthy();
    r.companyPriceContext!.reviewVersion = 'unrelated';
    expect(validPriceContext(r)).toBeNull();
    r.companyPriceContext!.reviewVersion = 'v1';
    r.companyPriceContext!.companies[0].companyId = 'NASDAQ:AAPL';
    expect(validPriceContext(r)).toBeNull();
  });
  it('rejects future bars, unknown source and a reaction rate without post-news bars', () => {
    for (const mutation of ['future', 'source', 'reaction', 'invalidClock']) {
      const r = result();
      const c = r.companyPriceContext!.companies[0];
      if (c.status !== 'available') throw new Error('fixture');
      if (mutation === 'future') c.latest.observedAt = '2026-10-23T20:00:00Z';
      if (mutation === 'source') c.news[0].evidenceId = 'unowned';
      if (mutation === 'reaction') c.news[0].changeRatePercent = '2.00';
      if (mutation === 'invalidClock') c.day.to = 'invalid';
      expect(validPriceContext(r)).toBeNull();
    }
  });
  it('binds the integrated business statement and rejects a future market comparison', () => {
    const r = result(),
      p = r.companyPriceContext!,
      business = r.editionReview!.companies[0],
      c = p.companies[0];
    business.stance = 'watch';
    business.sourceIds = ['s1'];
    business.judgment = { text: '실행 조건 확인', evidenceIds: ['s1'] };
    business.takeaway = { text: '관찰 유지.', evidenceIds: ['s1'] };
    p.outlookIntegrationVersion = 'zoop-company-price-outlook-v1';
    p.marketReference = {
      status: 'available',
      snapshotSha256: 'a'.repeat(64),
      note: '정확한 비교 기간',
      indicators: [
        {
          id: 'kospi',
          label: 'KOSPI',
          value: 90,
          unit: 'pt',
          valueKind: 'close',
          observedDate: '2026-10-21',
          observedAt: null,
          status: 'delayed',
          source: {
            name: '합성 지표',
            url: 'https://example.com',
            official: false,
          },
          baselineDate: '2026-10-19',
          changeRatePercent: '-10.00',
          text: '10/21 종가, 10/19 대비 -10.00%',
        },
      ],
    };
    c.outlook = {
      schemaVersion: 'zoop-company-price-outlook-v1',
      authorship: 'source_bound_composition',
      stance: 'watch',
      businessJudgment: structuredClone(business.judgment),
      evidenceIds: ['s1'],
      priceObservation: '종가 +2.00%.',
      nextCheck: '실행 조건을 확인합니다.',
      takeaway: '관찰 유지. 종가 +2.00%.',
      text: '실행 조건 확인 가격 측면에서는 종가 +2.00%. 실행 조건을 확인합니다.',
      marketNote: '국내 지수는 참고값입니다.',
    };
    expect(validPriceContext(r)).toBeTruthy();
    c.outlook.businessJudgment.text = '상승해서 사업 조건 확인';
    expect(validPriceContext(r)).toBeNull();
    c.outlook.businessJudgment = structuredClone(business.judgment);
    p.marketReference.indicators[0].baselineDate = '2026-10-23';
    expect(validPriceContext(r)).toBeNull();
  });
  it('shows the exact market comparison dates instead of inventing a previous-day return', () => {
    render(
      <PriceMarketReference
        reference={{
          status: 'available',
          snapshotSha256: 'a'.repeat(64),
          note: '해외기업 직접 비교지수 아님',
          indicators: [
            {
              id: 'kospi',
              label: 'KOSPI',
              value: 90,
              unit: 'pt',
              valueKind: 'close',
              observedDate: '2026-10-22',
              observedAt: null,
              status: 'delayed',
              source: {
                name: '합성 출처',
                url: 'https://example.com',
                official: false,
              },
              baselineDate: '2026-10-20',
              changeRatePercent: '-10.00',
              text: 'KOSPI 10/22 종가 90pt · 10/20 대비 -10.00% · 지연 자료',
            },
          ],
        }}
      />,
    );
    expect(
      screen.getByText(
        'KOSPI 10/22 종가 90pt · 10/20 대비 -10.00% · 지연 자료',
      ),
    ).toBeTruthy();
    expect(screen.getByRole('link').getAttribute('href')).toBe(
      'https://example.com',
    );
    expect(screen.getByText('해외기업 직접 비교지수 아님')).toBeTruthy();
  });
  it('keeps unavailable data explicit', () => {
    const c = company();
    render(
      <CompanyPriceContext
        context={{ ...c, status: 'unavailable', reason: '분봉 미제공' }}
        evening={false}
      />,
    );
    expect(screen.getByText('분봉 미제공')).toBeTruthy();
    expect(screen.queryByText('실제 주가 흐름과 함께 읽기')).toBeNull();
  });
});

function withAi(): BriefingResponse {
  const r = result(),
    company = r.editionReview!.companies[0];
  company.companyName = '합성 Meta';
  company.role = 'selected';
  company.sourceIds = ['s1'];
  const statement = {
    text: '사업과 실제 관측은 별도입니다.',
    evidenceIds: ['s1'],
  };
  r.aiPriceOutlooks = {
    schemaVersion: 'zoop-ai-price-outlooks-v1',
    model: 'gpt-6-luna',
    promptVersion: 'company-outlook-v5',
    verificationMode: 'independent_model',
    status: 'PASS',
    roundId: r.id,
    date: r.editionReview!.date,
    edition: 'evening',
    cutoff,
    resultVersion: 'ai-version',
    generatedAt: '2026-10-24T00:00:00Z',
    inputSha256: 'a'.repeat(64),
    reviewVersion: 'v1',
    priceContextVersion: 'price-v1',
    generationRequestDigest: 'b'.repeat(64),
    verificationRequestDigest: 'c'.repeat(64),
    projectionSha256: 'd'.repeat(64),
    companies: [
      {
        companyId: 'NASDAQ:META',
        companyName: '합성 Meta',
        role: 'selected',
        assessment: 'mixed',
        impact: statement,
        outlook: statement,
        conditions: [statement],
        risks: [statement],
        previous: { status: 'unavailable' },
        comparison: {
          ...statement,
          status: 'unavailable',
          previousResultVersion: null,
        },
      },
    ],
  };
  return r;
}
describe('v5 independently verified outlook binding', () => {
  it('accepts matching data and rejects stale price version or foreign-company evidence', () => {
    const r = withAi();
    expect(validAiPriceOutlooks(r)).toBeTruthy();
    r.aiPriceOutlooks!.priceContextVersion = 'stale';
    expect(validAiPriceOutlooks(r)).toBeNull();
    r.aiPriceOutlooks!.priceContextVersion = 'price-v1';
    r.aiPriceOutlooks!.companies[0].outlook = {
      text: '잘못된 근거',
      evidenceIds: ['foreign'],
    };
    expect(validAiPriceOutlooks(r)).toBeNull();
  });
  it('requires one company per target and the exact compared previous version', () => {
    const r = withAi();
    r.aiPriceOutlooks!.companies.push(r.aiPriceOutlooks!.companies[0]);
    expect(validAiPriceOutlooks(r)).toBeNull();
    const next = withAi();
    next.aiPriceOutlooks!.companies[0].comparison.previousResultVersion =
      'not-provided';
    expect(validAiPriceOutlooks(next)).toBeNull();
  });
  it('never accepts a withheld model draft as a verified outlook', () => {
    const r = withAi();
    r.aiPriceOutlooks!.status = 'WITHHELD';
    expect(validAiPriceOutlooks(r)).toBeNull();
    r.aiPriceOutlooks!.companies = [];
    expect(validAiPriceOutlooks(r)?.status).toBe('WITHHELD');
    delete r.aiPriceOutlooks;
    expect(validAiPriceOutlooks(r)).toBeNull();
  });
});

it('D-BRF-01/02 explicit selections authenticate reused prices using a separate frozen basis without reusing its business prose', () => {
  const r = result();
  r.companyPriceBasis = r.editionReview;
  delete r.editionReview;
  expect(validPriceContext(r)).toBeTruthy();
  r.companyPriceBasis!.resultVersion = 'wrong-review';
  expect(validPriceContext(r)).toBeNull();
});
