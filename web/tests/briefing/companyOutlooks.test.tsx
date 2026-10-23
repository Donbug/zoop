import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompanyOutlooks from '@/components/briefing/CompanyOutlooks';
import type { BriefingResponse } from '@/types/briefing';
import type { CompanyOutlooks as Layer } from '@/types/briefing/companyOutlook';

const statement = {
  text: '공급이 이행되는 경우 사업 기회를 검토합니다.',
  evidenceIds: ['e'],
};
const layer: Layer = {
  schemaVersion: 'zoop-company-outlooks-v1',
  roundId: 'r',
  edition: 'morning',
  cutoff: '2026-10-08T09:20:00+09:00',
  status: 'PASS',
  resultVersion: 'v',
  generatedAt: '2026-10-21T00:00:00Z',
  scopeNote: '합성 시험',
  companies: [
    {
      companyId: 'KRX:TEST',
      companyName: '합성 기업',
      issueIds: ['i'],
      assessment: 'mixed',
      facts: [{ text: '공급 계획을 발표했습니다.', evidenceIds: ['e'] }],
      impact: statement,
      outlook: statement,
      conditions: [
        { text: '규모와 시기 확인이 필요합니다.', evidenceIds: ['e'] },
      ],
      risks: [{ text: '수익성은 확인되지 않았습니다.', evidenceIds: ['e'] }],
      comparison: {
        text: '이전 동일 기업 판단이 없습니다.',
        evidenceIds: ['e'],
        status: 'unavailable',
        previousResultVersion: null,
      },
      observedMovement: { status: 'unavailable', reason: 'missing' },
      sources: [
        {
          evidenceId: 'e',
          documentId: 'd',
          documentVersion: 'sha',
          bodySha256: 'sha',
          title: '합성 원문',
          quote: '계획이며 확정되지 않았다.',
          url: 'https://example.com/source',
          publishedAt: '2026-10-08T08:00:00+09:00',
        },
      ],
    },
  ],
};
const result = {
  id: 'r',
  edition: 'morning',
  dataAsOf: layer.cutoff,
  companyOutlooks: layer,
  items: [{ eventId: 'i', companies: [{ id: 'KRX:TEST', name: '합성 기업' }] }],
} as BriefingResponse;

describe('D-BRF-01·02 company outlook', () => {
  it('distinguishes failed quote requests from a successful empty history', () => {
    const price = {
      companyId: 'KRX:TEST',
      cutoff: layer.cutoff,
      currency: 'KRW' as const,
      exchangeTimezone: 'Asia/Seoul',
      source: 'Yahoo Finance',
      official: false,
      note: '합성 시험',
      sources: [],
      status: 'unavailable' as const,
      reason: 'provider_request_failed',
      latest: null,
      baseline: null,
      comparisonStatus: 'unavailable' as const,
      change: null,
      changeRate: null,
    };
    const withPrice = (reason: string) => ({
      ...result,
      companyOutlooks: {
        ...layer,
        companies: [{ ...layer.companies[0], price: { ...price, reason } }],
      },
    });
    const { rerender } = render(
      <CompanyOutlooks result={withPrice('provider_request_failed')} compact />,
    );
    expect(
      screen.getByText(
        '시세 공급자 요청에 실패해 기업 시세를 확인하지 못했습니다.',
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText('회차 마감까지 확인된 기업 시세가 없습니다.'),
    ).toBeNull();
    rerender(
      <CompanyOutlooks result={withPrice('eligible_price_missing')} compact />,
    );
    expect(
      screen.getByText('회차 마감까지 확인된 기업 시세가 없습니다.'),
    ).toBeTruthy();
    expect(screen.queryByText(/시세 공급자 요청에 실패해/)).toBeNull();
  });

  it('leads with company outlook and preserves its conditions, risks and evidence', () => {
    render(<CompanyOutlooks result={result} compact={false} />);
    expect(
      screen.getByRole('heading', { name: '오늘의 기업별 전망' }),
    ).toBeTruthy();
    expect(screen.getByText('규모와 시기 확인이 필요합니다.')).toBeTruthy();
    expect(screen.getByText('수익성은 확인되지 않았습니다.')).toBeTruthy();
    expect(
      screen.getAllByRole('link', { hidden: true })[0].getAttribute('href'),
    ).toBe('https://example.com/source');
    expect(
      screen.getByText(/회차 마감까지 확인된 기업 시세가 없습니다/),
    ).toBeTruthy();
  });
  it('shows newly condensed text and keeps the entire original behind details', () => {
    const company = {
      ...layer.companies[0],
      reading: {
        status: 'PASS' as const,
        resultVersion: 'reading',
        brief: {
          text: '사업 기회는 있으나 공급 이행이 관건입니다.',
          evidenceIds: ['e'],
        },
        watch: { text: '공급 규모를 확인하세요.', evidenceIds: ['e'] },
        change: { text: '이전 판단 없음', evidenceIds: ['e'] },
      },
    };
    const { rerender } = render(
      <CompanyOutlooks
        result={{
          ...result,
          companyOutlooks: { ...layer, companies: [company] },
        }}
        compact
      />,
    );
    expect(screen.getByLabelText('합성 기업 짧은 읽기').textContent).toContain(
      '사업 기회는 있으나',
    );
    const detail = screen
      .getByText('자세히 · 기업 전망 전문과 근거')
      .closest('details')!;
    expect(detail.open).toBe(false);
    expect(detail.textContent).toContain(statement.text);
    rerender(<CompanyOutlooks result={result} compact={false} />);
    expect(
      screen.getByText('자세히 · 기업 전망 전문과 근거').closest('details')!
        .open,
    ).toBe(true);
  });
  it('does not replace an unavailable short reading with the full paragraph', () => {
    render(<CompanyOutlooks result={result} compact />);
    expect(screen.getByText(/검증된 짧은 요약이 없습니다/)).toBeTruthy();
    expect(
      screen.getByText('자세히 · 기업 전망 전문과 근거').closest('details')!
        .open,
    ).toBe(false);
  });
  it('shows a same-day morning price comparison and guards the round cutoff', () => {
    const price = {
      companyId: 'KRX:TEST',
      cutoff: layer.cutoff,
      currency: 'KRW' as const,
      exchangeTimezone: 'Asia/Seoul',
      source: 'Yahoo Finance',
      official: false,
      note: '합성 과거 이력',
      sources: [],
      status: 'available' as const,
      reason: null,
      latest: {
        value: '262000.00',
        observedAt: '2026-10-08T00:20:00Z',
        sessionDate: '2026-10-08',
        kind: 'five_minute_close' as const,
      },
      baseline: {
        value: '268500.00',
        observedAt: '2026-10-08T00:15:00Z',
        sessionDate: '2026-10-08',
        kind: 'five_minute_close' as const,
      },
      baselineKind: 'morning_cutoff' as const,
      comparisonStatus: 'available' as const,
      change: '-6500.00',
      changeRate: '-2.42',
    };
    const resultWithPrice = {
      ...result,
      companyOutlooks: {
        ...layer,
        companies: [{ ...layer.companies[0], price }],
      },
    };
    const { rerender } = render(
      <CompanyOutlooks result={resultWithPrice} compact />,
    );
    expect(screen.getByText(/아침 268,500원 → 262,000원/)).toBeTruthy();
    expect(screen.getByText(/아침 기준 대비/)).toBeTruthy();
    rerender(
      <CompanyOutlooks
        result={{
          ...result,
          companyOutlooks: {
            ...layer,
            companies: [
              {
                ...layer.companies[0],
                price: { ...price, cutoff: '2026-10-09T00:20:00Z' },
              },
            ],
          },
        }}
        compact
      />,
    );
    expect(screen.queryByText(/아침 268,500원 → 262,000원/)).toBeNull();
  });
  it('does not claim zero return when no US session has occurred', () => {
    const company = {
      ...layer.companies[0],
      price: {
        companyId: 'KRX:TEST',
        cutoff: layer.cutoff,
        currency: 'USD' as const,
        exchangeTimezone: 'America/New_York',
        source: 'Yahoo Finance',
        official: false,
        note: '합성 과거 이력',
        sources: [],
        status: 'available' as const,
        reason: null,
        latest: {
          value: '472.20',
          observedAt: '2026-10-07T20:00:00Z',
          sessionDate: '2026-10-07',
          kind: 'daily_close' as const,
        },
        baseline: null,
        comparisonStatus: 'no_new_session' as const,
        change: null,
        changeRate: null,
      },
    };
    render(
      <CompanyOutlooks
        result={{
          ...result,
          companyOutlooks: { ...layer, companies: [company] },
        }}
        compact
      />,
    );
    expect(screen.getByText(/아침 이후 새 정규장 관측 없음/)).toBeTruthy();
    expect(screen.queryByText('0%')).toBeNull();
  });
  it('does not show a forecast for another round, cutoff or selected company', () => {
    const { rerender } = render(
      <CompanyOutlooks result={{ ...result, id: 'other' }} compact />,
    );
    expect(screen.queryByRole('heading', { name: '합성 기업' })).toBeNull();
    rerender(
      <CompanyOutlooks
        result={{ ...result, dataAsOf: '2026-10-09T00:20:00Z' }}
        compact
      />,
    );
    expect(screen.queryByRole('heading', { name: '합성 기업' })).toBeNull();
    rerender(<CompanyOutlooks result={{ ...result, items: [] }} compact />);
    expect(screen.queryByRole('heading', { name: '합성 기업' })).toBeNull();
  });
  it('keeps a withheld result separate from the older market analysis', () => {
    render(
      <CompanyOutlooks
        result={{
          ...result,
          companyOutlooks: {
            ...layer,
            status: 'WITHHELD',
            companies: [],
            reason: '근거 검증 보류',
          },
        }}
        compact
      />,
    );
    expect(screen.getByText('근거 검증 보류')).toBeTruthy();
    expect(screen.queryByRole('article')).toBeNull();
  });
});

const specific = {
  ...layer.companies[0],
  reading: {
    schemaVersion: 'zoop-company-reading-v2' as const,
    status: 'PASS' as const,
    resultVersion: 'reading-v2-test',
    brief: {
      text: '증설은 장비 공급능력 확대의 조건부 근거입니다.',
      evidenceIds: ['e'],
    },
    fact: {
      text: '합성 기업이 새 생산라인 증설 계획을 발표했습니다.',
      evidenceIds: ['e'],
    },
    watch: {
      text: '실제 가동이 확인되면 공급 확대 판단을 강화합니다.',
      evidenceIds: ['e'],
    },
    background: {
      text: '기존 생산능력 수치는 제공되지 않았습니다.',
      evidenceIds: ['e'],
    },
    change: {
      text: '비교할 같은 기업의 이전 판단이 없습니다.',
      evidenceIds: ['e'],
    },
  },
};
describe('D-BRF-01/02 specific company reading v2', () => {
  it('shows judgment, new fact and next condition before collapsed background and evidence', () => {
    render(
      <CompanyOutlooks
        result={{
          ...result,
          companyOutlooks: { ...layer, companies: [specific] },
        }}
        compact
      />,
    );
    const card = screen.getByLabelText('합성 기업 판단과 새 사실');
    const text = card.textContent!;
    expect(text.indexOf('한 줄 판단')).toBeLessThan(text.indexOf('새 사실'));
    expect(text.indexOf('새 사실')).toBeLessThan(
      text.indexOf('다음 확인 조건'),
    );
    expect(
      screen.getByText('배경·이전 판단과의 연결·문장 근거').closest('details')!
        .open,
    ).toBe(false);
    expect(screen.getAllByText(specific.reading.background.text).length).toBe(
      1,
    );
    expect(
      screen.getByText('자세히 · 기업 전망 전문과 근거').closest('details')!
        .open,
    ).toBe(false);
  });
  it.each(['WITHHELD', 'missing_fact', 'foreign_evidence'])(
    'does not expose unverified v2 text for %s',
    (state) => {
      const company = structuredClone(specific);
      if (state === 'WITHHELD')
        (company.reading as { status: string }).status = state;
      if (state === 'missing_fact') company.reading.fact.text = '';
      if (state === 'foreign_evidence')
        company.reading.fact.evidenceIds = ['another-company'];
      render(
        <CompanyOutlooks
          result={{
            ...result,
            companyOutlooks: { ...layer, companies: [company] },
          }}
          compact
        />,
      );
      expect(screen.queryByLabelText('합성 기업 판단과 새 사실')).toBeNull();
      expect(
        screen.getByText(/검증된 새 문안을 표시할 수 없습니다/),
      ).toBeTruthy();
      expect(screen.getByText('자세히 · 기업 전망 전문과 근거')).toBeTruthy();
    },
  );
});
