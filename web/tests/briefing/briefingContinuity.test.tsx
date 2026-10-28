import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import BriefingContinuity from '@/components/briefing/BriefingContinuity';
import { hasOnlyKnownLimitations } from '@/components/briefing/briefingLimitations';
import type { BriefingContinuity as Continuity } from '@/types/briefing';

// D-BRF-01·02 synthetic references: no invented market/forecast data.
const base: Continuity = {
  schemaVersion: 'importance-continuity-v1',
  roundId: 'synthetic',
  cutoff: '2026-10-21T08:30:00Z',
  mode: 'reference',
  importanceFloor: 1,
  message: '확인한 범위에서 핵심 미선정 · 기업 참고 자료',
  coverage: {
    status: 'limited',
    confirmedDocuments: 19,
    message: '수집한 19건 범위이며 전체 시장을 뜻하지 않습니다.',
  },
  references: [
    {
      issueId: 'synthetic-one',
      title: '합성기업 관련 참고 소식',
      importance: 1,
      label: '계획·전망 자료 · 확정 결과 아님',
      companies: [{ id: 'TEST:A', name: '합성기업' }],
      sources: [
        {
          evidenceId: 'e',
          documentId: 'd',
          documentVersion: 'v',
          quote: '[합성] 원문에 있는 계획이며 완료가 아닙니다.',
          url: 'https://example.com/news',
          dateContext: { publishedAt: '2026-10-21T03:00:00Z' },
        },
      ],
    },
  ],
  recap: {
    status: 'unavailable',
    previousRoundId: null,
    dataAsOf: null,
    message: '검증된 이전 발행본이 없습니다.',
    items: [],
  },
  watchConditions: [
    { text: '공식 발표와 실제 이행 여부 확인', kind: 'verification_check' },
  ],
  forecast: {
    status: 'unavailable',
    message: '새 전망을 생성하지 않았습니다.',
  },
};
describe('quiet briefing continuity', () => {
  it('keeps exact sources expandable and never calls reference plans confirmed results', () => {
    render(
      <MemoryRouter>
        <BriefingContinuity value={base} compact />
      </MemoryRouter>,
    );
    expect(screen.getByText('합성기업 관련 참고 소식')).not.toBeNull();
    expect(screen.getByText(/계획·전망 자료 · 확정 결과 아님/)).not.toBeNull();
    const quote = screen.getByText(
      '[합성] 원문에 있는 계획이며 완료가 아닙니다.',
    );
    expect(quote.closest('details')?.hasAttribute('open')).toBe(false);
    expect(
      screen.getByRole('link', { name: '원문 열기' }).getAttribute('href'),
    ).toBe('https://example.com/news');
    expect(screen.getByText('검증된 이전 발행본이 없습니다.')).not.toBeNull();
    expect(screen.getByText('새 전망을 생성하지 않았습니다.')).not.toBeNull();
  });
  it('separately announces insufficient collection and does not fabricate references', () => {
    render(
      <MemoryRouter>
        <BriefingContinuity
          value={{
            ...base,
            mode: 'coverage_limited',
            references: [],
            message: '수집 실패로 판단 불가',
            coverage: {
              status: 'insufficient',
              confirmedDocuments: 0,
              message: '새 소식 부재와 다릅니다.',
            },
          }}
          compact
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole('heading', { name: '수집·확인 범위 부족' }),
    ).not.toBeNull();
    expect(screen.queryByText('합성기업 관련 참고 소식')).toBeNull();
  });
  it('discloses old conditions as old and links the exact previous date and edition', () => {
    render(
      <MemoryRouter>
        <BriefingContinuity
          value={{
            ...base,
            mode: 'recap',
            references: [],
            recap: {
              ...base.recap,
              status: 'available',
              previousRoundId: 'prior',
              date: '2026-10-21',
              edition: 'morning',
              dataAsOf: '2026-10-21T00:20:00Z',
            },
            watchConditions: [
              {
                text: '당시 계약 이행 여부',
                kind: 'previous_condition',
                companyName: '합성기업',
              },
            ],
          }}
          compact
        />
      </MemoryRouter>,
    );
    expect(
      screen
        .getByRole('link', { name: '이전 브리핑 전문 보기' })
        .getAttribute('href'),
    ).toBe('/briefing?date=2026-10-21&edition=morning&reading=full');
    expect(screen.getByText('(이전 회차의 확인 조건)')).not.toBeNull();
  });
});

it('distinguishes retrospective source scope from a real collection outage', () => {
  const detail = {
    section: 'sourceCoverage',
    message: '과거 자료 확인 범위',
    retryable: false,
    asOf: null,
  };
  expect(
    hasOnlyKnownLimitations([
      { ...detail, code: 'PUBLICATION_CLOCK_SIMULATION' },
    ]),
  ).toBe(true);
  expect(
    hasOnlyKnownLimitations([{ ...detail, code: 'COLLECTION_FAILED' }]),
  ).toBe(false);
  expect(
    hasOnlyKnownLimitations([
      { ...detail, code: 'PUBLICATION_CLOCK_SIMULATION', retryable: true },
    ]),
  ).toBe(false);
});

it('shows a short verified reference unchanged, including estimated qualifiers', () => {
  render(
    <MemoryRouter>
      <BriefingContinuity
        value={{ ...base, schemaVersion: 'importance-continuity-v2' }}
        compact
      />
    </MemoryRouter>,
  );
  const quotes = screen.getAllByText(
    '[합성] 원문에 있는 계획이며 완료가 아닙니다.',
  );
  expect(quotes.some((q) => q.closest('details') === null)).toBe(true);
});
