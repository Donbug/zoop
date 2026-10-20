import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import PublishedBriefing from '@/components/briefing/PublishedBriefing';
import { useAuthStore } from '@/stores/useAuthStore';
import type {
  BriefingResponse,
  PreviousBriefingComparison,
  PreviousBriefingComparisonItem,
} from '@/types/briefing';
import { createFakeServer, json } from '../support/fakeServer';

// D-BRF-01·02: 합성 비교 자료. 이슈의 선정 여부이며 수익률/전망 결과가 아니다.
const previousItem = (
  overrides: Partial<PreviousBriefingComparisonItem> = {},
): PreviousBriefingComparisonItem => ({
  title: '계속 선정된 합성 이슈',
  eventId: 'continuing-issue',
  eventTime: null,
  timePrecision: 'unknown',
  reportedAt: '2026-10-07T17:00:00+09:00',
  companyNames: ['합성 기업'],
  change: 'continuing',
  rank: 1,
  previousRank: 2,
  evidenceCount: 3,
  previousEvidenceCount: 1,
  ...overrides,
});

const previous = (items = [previousItem()]): PreviousBriefingComparison => ({
  status: 'available',
  previousRoundId: 'brf-2026-10-07-evening',
  previousPublishedAt: '2026-10-07T08:31:00Z',
  previousDataAsOf: '2026-10-07T08:30:00Z',
  comparisonBasis: 'event_identity',
  forecastEvaluation: {
    status: 'unavailable',
    reason: '전망 조건과 관측 결과가 연결되지 않았습니다.',
  },
  items,
});

function briefing(overrides: Partial<BriefingResponse> = {}): BriefingResponse {
  return {
    id: 'brf-2026-10-08-morning',
    date: '2026-10-08',
    edition: 'morning',
    status: 'published',
    scheduledAt: '2026-10-08T09:20:00+09:00',
    publishedAt: '2026-10-08T09:21:00+09:00',
    generatedAt: '2026-10-08T09:21:00+09:00',
    dataAsOf: '2026-10-08T09:20:00+09:00',
    graphVersion: 'fixed-v1',
    items: [],
    marketSummary: { status: 'unavailable', reason: '합성 시장 요약 없음' },
    marketVariables: { status: 'unavailable', reason: '합성 지표 없음' },
    sinceMorning: null,
    previousComparison: previous(),
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'fixture',
      asOf: '2026-10-08T09:20:00+09:00',
      graphVersion: 'fixed-v1',
      requestId: 'fixture-request',
      partial: false,
      failures: [],
    },
    ...overrides,
  };
}

function setup(response = briefing()) {
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings', () => json(response));
  render(
    <MemoryRouter>
      <PublishedBriefing date={response.date} edition={response.edition} />
    </MemoryRouter>,
  );
  return server;
}

beforeEach(() => useAuthStore.getState().clearSession());

describe('D-BRF-01 이전 퇴근 브리핑 대비', () => {
  it('출근 회차의 고정 이전 회차·기준시각·근거와 순위 변화를 조회 결과대로 표시한다', async () => {
    setup();
    const section = await screen.findByRole('region', {
      name: /이전 퇴근 브리핑 대비/,
    });
    expect(
      within(section).getByText(
        '비교 회차 데이터 기준 2026-10-07 17:30 KST · 발행 2026-10-07 17:31 KST',
      ),
    ).toBeTruthy();
    expect(within(section).getByText('이어짐')).toBeTruthy();
    expect(within(section).getByText('근거 1건 → 3건')).toBeTruthy();
    expect(within(section).getByText('선정 순위 2 → 1')).toBeTruthy();
    expect(
      within(section).getByText(
        '전망 결과 평가: 전망 조건과 관측 결과가 연결되지 않았습니다.',
      ),
    ).toBeTruthy();
    expect(within(section).getByRole('note').textContent).toContain(
      '빠짐이 악재나 사건의 해소를 뜻하지 않아요.',
    );
    expect(
      within(section)
        .getByRole('link', { name: '이전 퇴근 브리핑 보기' })
        .getAttribute('href'),
    ).toBe('/briefing?date=2026-10-07&edition=evening');
    expect(screen.queryByRole('region', { name: /아침 대비 변화/ })).toBeNull();
  });

  it('이전 퇴근에 없던 이슈·계속된 이슈·선정에서 빠진 이슈를 각각 구분한다', async () => {
    setup(
      briefing({
        previousComparison: previous([
          previousItem({
            title: '새 이슈',
            eventId: 'new-issue',
            change: 'new',
            previousRank: null,
            previousEvidenceCount: null,
          }),
          previousItem(),
          previousItem({
            title: '이전 이슈',
            eventId: 'dropped-issue',
            change: 'dropped',
            rank: null,
            evidenceCount: null,
            previousEvidenceCount: 2,
          }),
        ]),
      }),
    );
    const section = await screen.findByRole('region', {
      name: /이전 퇴근 브리핑 대비/,
    });
    const rows = within(section).getAllByRole('listitem');
    expect(within(rows[0]).getByText('신규')).toBeTruthy();
    expect(within(rows[1]).getByText('이어짐')).toBeTruthy();
    expect(within(rows[2]).getByText('빠짐')).toBeTruthy();
    expect(
      within(rows[2]).getByText('이번 회차 핵심 이슈에는 없어요 · 근거 2건'),
    ).toBeTruthy();
  });

  it('비교할 이전 발행 회차가 없으면 서버의 이유를 표시한다', async () => {
    setup(
      briefing({
        previousComparison: {
          status: 'unavailable',
          reason: '이전에 발행된 퇴근 브리핑이 없습니다.',
        },
      }),
    );
    const section = await screen.findByRole('region', {
      name: /이전 퇴근 브리핑 대비/,
    });
    expect(
      within(section).getByText('이전에 발행된 퇴근 브리핑이 없습니다.'),
    ).toBeTruthy();
    expect(within(section).queryByRole('list')).toBeNull();
    expect(within(section).queryByRole('link')).toBeNull();
  });

  it('과거 응답에 비교가 없을 때 비교 결과를 만들지 않는다', async () => {
    setup(briefing({ previousComparison: undefined }));
    const section = await screen.findByRole('region', {
      name: /이전 퇴근 브리핑 대비/,
    });
    expect(
      within(section).getByText('이전 퇴근 브리핑과 비교한 정보가 없어요.'),
    ).toBeTruthy();
    expect(within(section).queryByRole('list')).toBeNull();
  });

  it('실제로 비어 있는 비교 목록과 비교 미제공을 구분한다', async () => {
    setup(briefing({ previousComparison: previous([]) }));
    const section = await screen.findByRole('region', {
      name: /이전 퇴근 브리핑 대비/,
    });
    expect(within(section).getByText('0건')).toBeTruthy();
    expect(
      within(section).getByText(
        '이전 퇴근 브리핑과 달라진 핵심 이슈가 없어요.',
      ),
    ).toBeTruthy();
    expect(within(section).getByRole('link')).toBeTruthy();
  });

  it('아직 발행하지 않은 회차의 이전 비교를 노출하지 않는다', async () => {
    setup(briefing({ status: 'not_ready' }));
    expect(
      await screen.findByRole('heading', { name: '출근 브리핑' }),
    ).toBeTruthy();
    expect(
      screen.queryByRole('region', { name: /이전 퇴근 브리핑 대비/ }),
    ).toBeNull();
    expect(screen.queryByText('계속 선정된 합성 이슈')).toBeNull();
  });

  it('퇴근 회차는 같은 날 출근 비교만 사용하고 이전 퇴근 필드를 섞지 않는다', async () => {
    setup(
      briefing({
        id: 'brf-2026-10-08-evening',
        edition: 'evening',
        sinceMorning: {
          status: 'available',
          morningRoundId: 'brf-2026-10-08-morning',
          morningPublishedAt: '2026-10-08T09:21:00+09:00',
          morningDataAsOf: '2026-10-08T09:20:00+09:00',
          items: [],
        },
      }),
    );
    const section = await screen.findByRole('region', {
      name: /아침 대비 변화/,
    });
    expect(
      within(section).getByText(
        '비교 회차 데이터 기준 2026-10-08 09:20 KST · 발행 2026-10-08 09:21 KST',
      ),
    ).toBeTruthy();
    expect(
      within(section)
        .getByRole('link', { name: '출근 브리핑 보기' })
        .getAttribute('href'),
    ).toBe('/briefing?date=2026-10-08&edition=morning');
    expect(
      screen.queryByRole('region', { name: /이전 퇴근 브리핑 대비/ }),
    ).toBeNull();
    expect(screen.queryByText('계속 선정된 합성 이슈')).toBeNull();
  });
});
