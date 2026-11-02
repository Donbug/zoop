import { useAuthStore } from '@/stores/useAuthStore';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import BriefingPage from '@/pages/briefing/BriefingPage';
import type {
  BriefingResponse,
  MarketIndicator,
  SinceMorningItem,
} from '@/types/briefing';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';

beforeEach(() => {
  // Public briefing tests start after guest-session resolution; bootstrap has its own test.
  useAuthStore.getState().clearSession();
});

// 합성 fixture. 와이어프레임 D-BRF-02(2026-09-17 퇴근)의 예시 수치를 따른다.
const kospi: MarketIndicator = {
  id: 'kospi',
  label: 'KOSPI',
  unit: 'pt',
  status: 'ok',
  value: 6715.41,
  valueKind: 'close',
  observedDate: '2026-09-17',
  observedAt: null,
  baseline: { value: 6717.97, date: '2026-09-16', at: null },
  change: -2.56,
  changeRate: -0.0004,
  source: { name: '합성 출처', official: false, delayNote: null },
  reason: null,
};

function sinceItem(overrides: Partial<SinceMorningItem>): SinceMorningItem {
  return {
    title: '삼성전자, One UI 9 공식 버전 업데이트 시작',
    eventId: 'ev-1',
    eventTime: null,
    timePrecision: 'unknown',
    reportedAt: '2026-09-17T08:00:00Z',
    companyNames: ['삼성전자'],
    change: 'new',
    rank: 1,
    morningRank: null,
    evidenceCount: 1,
    morningEvidenceCount: null,
    ...overrides,
  };
}

function evening(overrides: Partial<BriefingResponse> = {}): BriefingResponse {
  return {
    id: 'brf-2026-09-17-evening',
    date: '2026-09-17',
    edition: 'evening',
    status: 'published',
    scheduledAt: '2026-09-17T18:10:00+09:00',
    publishedAt: '2026-09-17T18:11:00+09:00',
    generatedAt: '2026-09-17T18:11:00+09:00',
    dataAsOf: '2026-09-17T18:10:00+09:00',
    graphVersion: 'v1',
    marketSummary: {
      text: '합성 퇴근 시장 요약',
      evidenceIds: ['e'],
      generatedAt: '2026-09-17T18:11:00+09:00',
      resultVersion: 'v1',
    },
    marketVariables: { status: 'available', indicators: [kospi] },
    items: [
      {
        title: '삼성전자, One UI 9 공식 버전 업데이트 시작',
        eventId: 'ev-1',
        eventTime: '2026-09-16',
        timePrecision: 'day',
        companies: [],
        evidenceIds: ['e'],
        summary: { status: 'unavailable', reason: '검증된 요약 없음' },
        rank: 1,
        reason:
          '이번 회차 데이터 창 안의 승인 이슈 5건 중 사건 시각이 1번째로 최근입니다',
        evidenceCount: 1,
      },
    ],
    sinceMorning: {
      status: 'available',
      morningRoundId: 'brf-2026-09-17-morning',
      morningPublishedAt: '2026-09-17T07:41:00+09:00',
      morningDataAsOf: '2026-09-17T07:40:00+09:00',
      items: [
        sinceItem({}),
        sinceItem({
          eventId: 'ev-2',
          title: 'HBM4 공급 계약',
          change: 'continuing',
          rank: 2,
          morningRank: 1,
          evidenceCount: 3,
          morningEvidenceCount: 1,
          reportedAt: '2026-09-16',
        }),
        sinceItem({
          eventId: 'ev-3',
          title: 'NVIDIA MLPerf 결과 발표',
          change: 'dropped',
          rank: null,
          morningRank: 2,
          evidenceCount: null,
          morningEvidenceCount: 2,
          reportedAt: null,
        }),
      ],
    },
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'fixture',
      asOf: '2026-09-17T18:10:00+09:00',
      graphVersion: 'v1',
      requestId: 'r',
      partial: false,
      failures: [],
    },
    ...overrides,
  };
}

function setup(response: BriefingResponse, url: string) {
  // These regressions exercise the preserved full view.
  if (!new URL(url, 'http://localhost').searchParams.has('reading'))
    url += (url.includes('?') ? '&' : '?') + 'reading=full';
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings', () => json(response));
  render(
    <MemoryRouter initialEntries={[url]}>
      <BriefingPage />
    </MemoryRouter>,
  );
  return server;
}

describe('D-BRF-02 퇴근 브리핑 / FS029 FS030 FS031 FS033', () => {
  it('퇴근 회차를 요청하고 같은 형식으로 시장 요약·지표·핵심 이슈를 보여 준다', async () => {
    const server = setup(
      evening(),
      '/briefing?date=2026-09-17&edition=evening',
    );

    expect(await screen.findByText('합성 퇴근 시장 요약')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '퇴근 브리핑' })).toBeTruthy();
    expect(document.querySelector('[data-screen-id="D-BRF-02"]')).toBeTruthy();
    const query = server.requests[0].query;
    expect(query.get('edition')).toBe('evening');
    expect(query.get('date')).toBe('2026-09-17');
    expect(screen.getByText(/예정 18:10/)).toBeTruthy();
    expect(screen.getByText('6,715.41 pt')).toBeTruthy();
    expect(screen.getByText(/▼ -2.56 \(-0.04%\)/)).toBeTruthy();
    expect(
      screen.getByText('1. 삼성전자, One UI 9 공식 버전 업데이트 시작'),
    ).toBeTruthy();
  });

  it('아침 대비 변화를 신규·이어짐·빠짐 표지와 근거 수 변화로 보여 준다', async () => {
    setup(evening(), '/briefing?date=2026-09-17&edition=evening');

    const section = await screen.findByRole('region', {
      name: /아침 대비 변화/,
    });
    expect(within(section).getByText('3건')).toBeTruthy();
    const rows = within(section).getAllByRole('listitem');
    expect(within(rows[0]).getByText('신규')).toBeTruthy();
    expect(within(rows[0]).getByText('보도 17:00')).toBeTruthy();
    expect(within(rows[0]).getByText('근거 1건')).toBeTruthy();
    expect(within(rows[1]).getByText('이어짐')).toBeTruthy();
    expect(within(rows[1]).getByText('보도 2026-09-16')).toBeTruthy();
    expect(within(rows[1]).getByText('근거 1건 → 3건')).toBeTruthy();
    expect(within(rows[2]).getByText('빠짐')).toBeTruthy();
    expect(within(rows[2]).getByText('보도 시각 미상')).toBeTruthy();
    expect(
      within(rows[2]).getByText('이번 회차 핵심 이슈에는 없어요 · 근거 2건'),
    ).toBeTruthy();
    expect(
      within(section)
        .getByRole('link', { name: '출근 브리핑 보기' })
        .getAttribute('href'),
    ).toBe('/briefing?date=2026-09-17&edition=morning');
  });

  it('같은 날 출근 회차와 비교할 수 없으면 이유만 보여 준다', async () => {
    setup(
      evening({
        sinceMorning: {
          status: 'unavailable',
          reason: '같은 날 발행된 출근 브리핑이 없어요.',
        },
      }),
      '/briefing?date=2026-09-17&edition=evening',
    );

    expect(
      await screen.findByText('같은 날 발행된 출근 브리핑이 없어요.'),
    ).toBeTruthy();
    expect(screen.queryByRole('link', { name: '출근 브리핑 보기' })).toBeNull();
  });

  it('달라진 이슈가 없으면 빈 상태를, 출근 회차에는 비교 영역을 두지 않는다', async () => {
    setup(
      evening({
        sinceMorning: {
          status: 'available',
          morningRoundId: 'brf-2026-09-17-morning',
          morningPublishedAt: null,
          morningDataAsOf: '2026-09-17T07:40:00+09:00',
          items: [],
        },
      }),
      '/briefing?date=2026-09-17&edition=evening',
    );
    expect(
      await screen.findByText('출근 브리핑과 달라진 핵심 이슈가 없어요.'),
    ).toBeTruthy();
  });

  it('출근 회차에는 아침 대비 변화 영역이 없다', async () => {
    setup(
      evening({ edition: 'morning', sinceMorning: null }),
      '/briefing?date=2026-09-17&edition=morning',
    );
    expect(await screen.findByText('합성 퇴근 시장 요약')).toBeTruthy();
    expect(screen.queryByRole('region', { name: /아침 대비 변화/ })).toBeNull();
  });

  it('퇴근 회차가 아직 준비되지 않았으면 내용 없이 상태와 다시 시도를 보여 준다', async () => {
    setup(
      evening({
        status: 'not_ready',
        notice: {
          kind: 'not_ready',
          message: '18:10 발행 전이에요.',
          reason: null,
          at: null,
        },
      }),
      '/briefing?date=2026-09-17&edition=evening',
    );
    expect(await screen.findByText('18:10 발행 전이에요.')).toBeTruthy();
    expect(screen.queryByText('합성 퇴근 시장 요약')).toBeNull();
    expect(screen.queryByRole('region', { name: /아침 대비 변화/ })).toBeNull();
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy();
  });
});

describe('D-BRF-02 회차 전환 및 재조회 회귀', () => {
  it('퇴근 회차 로딩 중 출근으로 전환하면 늦게 온 퇴근 내용을 버린다', async () => {
    const server = createFakeServer();
    const pending = deferred<Response>();
    server.on('GET', '/api/v1/briefings', ({ query }) =>
      query.get('edition') === 'evening'
        ? pending.promise
        : json(
            evening({
              edition: 'morning',
              sinceMorning: null,
              marketSummary: {
                status: 'unavailable',
                reason: '전환된 출근 회차',
              },
            }),
          ),
    );
    render(
      <MemoryRouter
        initialEntries={[
          '/briefing?date=2026-09-17&edition=evening&reading=full',
        ]}
      >
        <BriefingPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(server.requests).toHaveLength(1));
    expect(screen.getByText('브리핑을 불러오고 있어요.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '출근' }));
    await screen.findByText('전환된 출근 회차');
    await act(async () => pending.resolve(json(evening())));
    expect(screen.queryByText('합성 퇴근 시장 요약')).toBeNull();
    expect(screen.queryByRole('region', { name: /아침 대비 변화/ })).toBeNull();
    expect(screen.getByRole('heading', { name: '출근 브리핑' })).toBeTruthy();
  });

  it('부분 실패 재조회가 권한 오류이면 이전 내용을 숨기고 재시도로 복구한다', async () => {
    const data = evening();
    const server = setup(
      evening({
        metadata: {
          ...data.metadata,
          partial: true,
          failures: [
            {
              section: 'marketVariables',
              code: 'FIXTURE',
              message: '합성 지표 실패',
              retryable: true,
              asOf: null,
            },
          ],
        },
      }),
      '/briefing?date=2026-09-17&edition=evening',
    );
    await screen.findByText('합성 퇴근 시장 요약');
    server.on('GET', '/api/v1/briefings', () => apiError(403, 'FORBIDDEN'));
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect((await screen.findByRole('alert')).textContent).toContain('권한');
    expect(screen.queryByText('합성 퇴근 시장 요약')).toBeNull();
    expect(screen.queryByRole('region', { name: /아침 대비 변화/ })).toBeNull();
    server.on('GET', '/api/v1/briefings', () => json(evening()));
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('합성 퇴근 시장 요약');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('누락된 비교 근거 수를 0건으로 바꾸지 않고 같은 제목은 기업으로 구분한다', async () => {
    setup(
      evening({
        sinceMorning: {
          status: 'available',
          morningRoundId: 'brf-2026-09-17-morning',
          morningPublishedAt: null,
          morningDataAsOf: '2026-09-17T07:40:00+09:00',
          items: [
            sinceItem({
              title: '공급 계약',
              evidenceCount: null,
              companyNames: ['삼성전자'],
            }),
            sinceItem({
              title: '공급 계약',
              eventId: 'ev-other',
              companyNames: ['SK하이닉스'],
              evidenceCount: 0,
            }),
          ],
        },
      }),
      '/briefing?date=2026-09-17&edition=evening',
    );
    const comparison = await screen.findByRole('region', {
      name: /아침 대비 변화/,
    });
    expect(
      within(comparison).getByText('관련 기업 삼성전자 · 근거 확인되지 않음'),
    ).toBeTruthy();
    expect(
      within(comparison).getByText('관련 기업 SK하이닉스 · 근거 0건'),
    ).toBeTruthy();
  });
});
