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
      screen.getByText(/가격 흐름·예측 적중 여부는 평가하지 않았습니다/),
    ).toBeTruthy();
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
