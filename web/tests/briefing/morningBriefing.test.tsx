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
import type { BriefingResponse, MarketIndicator } from '@/types/briefing';
import {
  createFakeServer,
  json,
  apiError,
  deferred,
} from '../support/fakeServer';

beforeEach(() => {
  // Public briefing tests start after guest-session resolution; bootstrap has its own test.
  useAuthStore.getState().clearSession();
});

const unavailable = {
  status: 'unavailable',
  reason: '검증된 요약 없음',
} as const;
const indicator: MarketIndicator = {
  id: 'kospi',
  label: 'KOSPI',
  unit: 'pt',
  status: 'ok',
  value: 2600,
  valueKind: 'close',
  observedDate: '2026-10-13',
  observedAt: null,
  baseline: { value: 2500, date: '2026-10-12', at: null },
  change: 100,
  changeRate: 0.04,
  source: { name: '합성 출처', official: false, delayNote: null },
  reason: null,
};
function round(overrides: Partial<BriefingResponse> = {}): BriefingResponse {
  return {
    id: 'fixture-round',
    date: '2026-10-14',
    edition: 'morning',
    status: 'published',
    scheduledAt: '2026-10-14T07:40:00+09:00',
    publishedAt: '2026-10-14T07:42:00+09:00',
    generatedAt: '2026-10-14T07:41:00+09:00',
    dataAsOf: '2026-10-14T07:40:00+09:00',
    graphVersion: 'fixture-version',
    marketSummary: {
      text: '합성 시장 요약',
      evidenceIds: ['fixture-evidence'],
      generatedAt: '2026-10-14T07:41:00+09:00',
      resultVersion: 'fixture-v1',
    },
    marketVariables: { status: 'available', indicators: [indicator] },
    items: [
      {
        title: '합성 핵심 이슈',
        eventId: 'fixture-event',
        eventTime: null,
        timePrecision: 'unknown',
        companies: [],
        evidenceIds: ['fixture-evidence'],
        summary: unavailable,
        rank: 1,
        reason: '합성 선정 이유',
        evidenceCount: 1,
      },
    ],
    sinceMorning: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'fixture',
      asOf: '2026-10-14T07:40:00+09:00',
      graphVersion: 'fixture-version',
      requestId: 'fixture-request',
      partial: false,
      failures: [],
    },
    ...overrides,
  };
}
function setup(response = round(), url = '/briefing') {
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings', () => json(response));
  render(
    <MemoryRouter initialEntries={[url]}>
      <BriefingPage />
    </MemoryRouter>,
  );
  return server;
}
describe('D-BRF-01 / FS028 FS030 FS031 FS033 FS035', () => {
  it('labels a stored historical replay and preserves missing market data', async () => {
    const response = round();
    setup({
      ...response,
      graphVersion: null,
      marketVariables: { status: 'unavailable', reason: '당시 지표 미수집' },
      metadata: {
        ...response.metadata,
        source: 'zoop-briefing-development-replay',
        graphVersion: null,
      },
    });
    const note = await screen.findByRole('note', { name: '개발 재생 안내' });
    expect(note.textContent).toContain('과거 수집 자료');
    expect(note.textContent).toContain('동일한 자료');
    expect(screen.getByText('당시 지표 미수집')).toBeTruthy();
    expect(screen.queryByText('2,600 pt')).toBeNull();
    expect(
      screen.getByRole('heading', { name: /합성 핵심 이슈/ }),
    ).toBeTruthy();
  });
  it('requests latest morning without a date and renders stored summary, times and fractional changes', async () => {
    const server = setup();
    await screen.findByText('합성 시장 요약');
    expect(screen.queryByRole('note', { name: '개발 재생 안내' })).toBeNull();
    expect(server.requests[0].query.get('edition')).toBe('morning');
    expect(server.requests[0].query.has('date')).toBe(false);
    expect(screen.getByText('2,600 pt')).toBeTruthy();
    expect(screen.getByText(/▲ \+100 \(\+4%\)/)).toBeTruthy();
    expect(screen.getByText(/발행일 2026-10-14/)).toBeTruthy();
    expect(screen.getByText(/데이터 기준.*KST/)).toBeTruthy();
    expect(screen.getByText(/선정 이유: 합성 선정 이유/)).toBeTruthy();
    expect(screen.getByText('발생 시각 미상')).toBeTruthy();
    expect(
      within(screen.getByRole('region', { name: '핵심 이슈' })).queryAllByRole(
        'listitem',
      ).length,
    ).toBeGreaterThan(0);
  });
  it.each(['published', 'not_ready'] as const)(
    'labels a per-round historical simulation with status %s',
    async (status) => {
      const response = round({ status });
      setup({
        ...response,
        metadata: {
          ...response.metadata,
          source: 'zoop-briefing-publication-clock-simulation',
        },
      });
      const note = await screen.findByRole('note', {
        name: '회차별 과거 시뮬레이션 안내',
      });
      expect(note.textContent).toContain('회차별로 나눈');
      expect(note.textContent).toContain('당시 본문과');
      expect(screen.queryByRole('note', { name: '개발 재생 안내' })).toBeNull();
    },
  );
  it.each(['not_ready', 'generating', 'failed', 'suspended'] as const)(
    'shows %s without exposing unpublished content',
    async (status) => {
      setup(
        round({
          status,
          notice: {
            kind: status,
            message: '회차 상태 안내',
            reason: '합성 사유',
            at: null,
          },
        }),
      );
      await screen.findByText(/회차 상태 안내/);
      expect(screen.queryByText('합성 시장 요약')).toBeNull();
      // 제공 중단은 관리자 해제 전까지 바뀌지 않으므로 다시 시도를 두지 않는다.
      if (status === 'suspended')
        expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull();
      else
        expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy();
    },
  );
  it('keeps available sections when one indicator fails, without presenting failed values', async () => {
    setup(
      round({
        marketVariables: {
          status: 'available',
          indicators: [
            indicator,
            {
              ...indicator,
              id: 'kosdaq',
              status: 'failed',
              value: 999,
              reason: '합성 지표 실패',
            },
            {
              ...indicator,
              id: 'usdkrw',
              status: 'delayed',
              value: 1300,
              unit: 'KRW',
              reason: '관측 지연',
            },
          ],
        },
      }),
    );
    await screen.findByText('합성 시장 요약');
    expect(screen.getByText('합성 지표 실패')).toBeTruthy();
    expect(screen.queryByText('999 pt')).toBeNull();
    expect(screen.getByText('1,300원')).toBeTruthy();
    expect(screen.getByText('지연')).toBeTruthy();
  });
  it('does not pad an empty round with fabricated issues', async () => {
    setup(
      round({
        items: [],
        emptyReason: 'no_issues_in_window',
        marketVariables: { status: 'unavailable', reason: '과거 지표 없음' },
      }),
    );
    await screen.findByText('이 회차의 선정 기준을 충족한 핵심 이슈가 없어요.');
    expect(screen.getByText('과거 지표 없음')).toBeTruthy();
  });
  it('recovers from network failure through retry', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings', () => apiError(503, 'TEMPORARY'));
    render(
      <MemoryRouter>
        <BriefingPage />
      </MemoryRouter>,
    );
    await screen.findByRole('alert');
    server.on('GET', '/api/v1/briefings', () => json(round()));
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('합성 시장 요약');
  });
  it.each([403, 404])('distinguishes HTTP %s', async (status) => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings', () => apiError(status, 'FIXTURE'));
    render(
      <MemoryRouter>
        <BriefingPage />
      </MemoryRouter>,
    );
    expect((await screen.findByRole('alert')).textContent).toContain(
      status === 403 ? '권한' : '아직 준비',
    );
  });
  it('ignores a late response after date changes', async () => {
    const server = createFakeServer();
    const pending = deferred<Response>();
    server.on('GET', '/api/v1/briefings', ({ query }) =>
      query.get('date') === '2026-10-13' ? pending.promise : json(round()),
    );
    render(
      <MemoryRouter initialEntries={['/briefing?date=2026-10-13']}>
        <BriefingPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(server.requests.length).toBe(1));
    fireEvent.change(screen.getByLabelText('날짜'), {
      target: { value: '2026-10-14' },
    });
    await screen.findByText('합성 시장 요약');
    await act(async () =>
      pending.resolve(
        json(
          round({
            date: '2026-10-13',
            marketSummary: { ...unavailable, reason: '오래된 응답' },
          }),
        ),
      ),
    );
    expect(screen.queryByText('오래된 응답')).toBeNull();
  });
  it('preserves original content alongside correction history', async () => {
    setup(
      round({
        corrections: [
          {
            id: 1,
            original: '합성 원문',
            corrected: '합성 정정',
            reason: '합성 사유',
            createdAt: '2026-10-14T09:00:00+09:00',
          },
        ],
      }),
    );
    await screen.findByText('발행 원문: 합성 원문');
    expect(screen.getByText('정정 내용: 합성 정정')).toBeTruthy();
  });
  it('preserves successful sections and permits retry for a partial response', async () => {
    const data = round();
    setup(
      round({
        metadata: {
          ...data.metadata,
          partial: true,
          failures: [
            {
              section: 'marketVariables',
              code: 'FIXTURE',
              message: '합성 부분 실패',
              retryable: true,
              asOf: null,
            },
          ],
        },
      }),
    );
    await screen.findByText('합성 부분 실패');
    expect(screen.getByText('합성 시장 요약')).toBeTruthy();
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy();
  });
  it('rejects a response for a different publication date', async () => {
    setup(round(), '/briefing?date=2026-10-13');
    await screen.findByRole('alert');
    expect(screen.queryByText('합성 시장 요약')).toBeNull();
  });
  it('shows at most three server-selected issues without reranking them', async () => {
    const item = round().items[0];
    setup(
      round({
        items: [1, 2, 3, 4].map((rank) => ({
          ...item,
          rank,
          eventId: `fixture-${rank}`,
          title: `합성 이슈 ${rank}`,
        })),
      }),
    );
    await screen.findByText('1. 합성 이슈 1');
    expect(screen.getByText('3. 합성 이슈 3')).toBeTruthy();
    expect(screen.queryByText('4. 합성 이슈 4')).toBeNull();
  });
});

it('hides the previous publication while a partial round is being retried', async () => {
  const data = round();
  const server = setup(
    round({
      metadata: {
        ...data.metadata,
        partial: true,
        failures: [
          {
            section: 'marketVariables',
            code: 'FIXTURE',
            message: '지표 일부 실패',
            retryable: true,
            asOf: null,
          },
        ],
      },
    }),
  );
  await screen.findByText('합성 시장 요약');
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/briefings', () => pending.promise);
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  expect(screen.queryByText('합성 시장 요약')).toBeNull();
  expect(screen.getByRole('status').textContent).toContain('불러오고');
  await act(async () => pending.resolve(json(round())));
  await screen.findByText('합성 시장 요약');
});

it('does not offer retry for a suspended round even with retryable section failures', async () => {
  const data = round();
  setup(
    round({
      status: 'suspended',
      metadata: {
        ...data.metadata,
        partial: true,
        failures: [
          {
            section: 'marketVariables',
            code: 'FIXTURE',
            message: '이전 지표 실패',
            retryable: true,
            asOf: null,
          },
        ],
      },
    }),
  );
  await screen.findByText('발행 중단');
  expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull();
  expect(screen.queryByText('합성 시장 요약')).toBeNull();
});
