import { act, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import CompanyDetailPage from '@/pages/company/CompanyDetailPage';
import { useAuthStore } from '@/stores/useAuthStore';
import { renderRoutes } from './support/renderRoutes';
import {
  createFakeServer,
  json,
  apiError,
  deferred,
} from './support/fakeServer';

vi.hoisted(() => vi.stubEnv('VITE_GRAPH_DATA_SOURCE', 'api'));
vi.mock('@/components/company/CompanyGraphPreview', () => ({
  default: () => <div />,
}));
const id = 'KRX:FIXTURE',
  at = '2026-10-06T03:00:00Z';
const metadata = {
  source: 'fixture',
  asOf: at,
  graphVersion: 'v1',
  partial: false,
  failures: [],
};
const source = {
  name: '합성 공급자',
  provider: 'fixture',
  symbol: 'FIXTURE',
  official: false,
  delayNote: null,
  url: null,
};
const company = {
  id,
  name: '합성 기업',
  ticker: 'FIXTURE',
  market: 'KRX',
  sector: '합성 업종',
  logoUrl: '/fixture-logo.svg',
  summary: null,
  metadata,
};
let server: ReturnType<typeof createFakeServer>;
const metrics = {
  status: 'available',
  companyId: id,
  source,
  asOf: at,
  items: [
    { code: 'per', label: 'PER', value: '12.35배', basis: '2026.06' },
    { code: 'pbr', label: 'PBR', value: '0.61배', basis: null },
  ],
};
const quote = {
  status: 'available',
  companyId: id,
  source,
  quote: {
    price: 120,
    currency: 'KRW',
    asOf: at,
    change: 2,
    changeRate: 0.02,
    volume: null,
    dayLow: null,
    dayHigh: null,
    fiftyTwoWeekLow: null,
    fiftyTwoWeekHigh: null,
    marketCap: 1200000,
  },
};
function member(name = 'fixture-member') {
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: { id: name, email: 'fixture@zoop.test', displayName: '합성 회원' },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: 'fixture-csrf',
    expiresAt: null,
  });
}
function lists(holding: boolean, watch: boolean) {
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      holdings: holding
        ? [
            {
              companyId: id,
              quantity: 1,
              avgPrice: 100,
              avgPriceCurrency: 'KRW',
              marketValue: 120,
              weight: null,
              quote: { status: 'available', currency: 'KRW' },
            },
          ]
        : [],
      mockAsOf: null,
      valuation: null,
      metadata,
    }),
  );
  server.on('GET', '/api/v1/me/settings', () =>
    json({
      mode: 'watchlist',
      watchlistIds: watch ? [id] : [],
      completed: true,
      tutorialCompleted: true,
      investor: true,
      version: 1,
    }),
  );
}
beforeEach(() => {
  useAuthStore.getState().clearSession();
  server = createFakeServer();
  server.on('GET', '/api/v1/companies/:id', (r) =>
    json({ ...company, id: r.params.id }),
  );
  server.on('GET', '/api/v1/companies', () =>
    json({ items: [company], nextCursor: null }),
  );
  server.on('GET', '/api/v1/companies/:id/quote', () => json(quote));
  server.on('GET', '/api/v1/companies/:id/metrics', () => json(metrics));
  server.on('GET', '/api/v1/companies/:id/prices', () =>
    json({ status: 'unavailable', reason: '합성 가격 없음' }),
  );
  server.on('GET', '/api/v1/events', () =>
    json({
      items: [],
      unknownTimeItems: [],
      nextCursor: null,
      metadata: { ...metadata, total: 0, excludedUnknownTime: 0 },
    }),
  );
  server.on('GET', '/api/v1/companies/:id/graph', () =>
    json({ nodes: [], edges: [], metadata: { ...metadata, truncated: false } }),
  );
  lists(false, false);
});
function open(extra = '') {
  return render(
    <MemoryRouter
      initialEntries={[
        `/companies/${encodeURIComponent(id)}?asOf=${encodeURIComponent(at)}&graphVersion=v1${extra}`,
      ]}
    >
      <Routes>
        <Route path="/companies/:id" element={<CompanyDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}
function header() {
  return within(screen.getByRole('region', { name: '기업 개요' }));
}

test.each([
  [true, false],
  [false, true],
  [true, true],
  [false, false],
])(
  'D-COM-01 45 shares holding=%s/watch=%s without a second settings request',
  async (holding, watch) => {
    member();
    lists(holding, watch);
    open();
    await screen.findByRole('heading', { name: company.name, level: 1 });
    await waitFor(() =>
      expect(server.calls('GET', '/api/v1/me/settings')).toHaveLength(1),
    );
    await screen.findByText('PER');
    expect(header().queryByText('보유') !== null).toBe(holding);
    expect(header().queryByText('관심') !== null).toBe(watch);
    expect(header().getByText(/합성 업종.*FIXTURE/)).toBeTruthy();
    expect(
      screen
        .getByRole('heading', { name: company.name })
        .parentElement?.parentElement?.querySelector('img')
        ?.getAttribute('src'),
    ).toBe('/fixture-logo.svg');
  },
);
test('D-COM-01 45 hides member badges and requests for guests', async () => {
  lists(true, true);
  open();
  await screen.findByText('PER');
  expect(header().queryByText('보유')).toBeNull();
  expect(header().queryByText('관심')).toBeNull();
  expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(0);
  expect(server.calls('GET', '/api/v1/me/settings')).toHaveLength(0);
});
test('D-COM-01 45 discards former member badges and late responses', async () => {
  member('old');
  lists(true, true);
  open();
  await waitFor(() => expect(header().getByText('관심')).toBeTruthy());
  const pending = deferred<Response>();
  lists(false, false);
  server.on('GET', '/api/v1/me/settings', () => pending.promise);
  await act(async () => member('next'));
  expect(header().queryByText('보유')).toBeNull();
  expect(header().queryByText('관심')).toBeNull();
  await act(async () => useAuthStore.getState().clearSession());
  await act(async () => pending.resolve(json({ watchlistIds: [id] })));
  expect(header().queryByText('관심')).toBeNull();
});
test('D-COM-01 42 shows latest metrics with source and basis but no snapshot query', async () => {
  open();
  await screen.findByText('12.35배');
  expect(screen.getByText('PBR')).toBeTruthy();
  expect(
    screen.getByRole('heading', { name: '주요 지표 · 최신 기준' }),
  ).toBeTruthy();
  const section = screen.getByRole('region', { name: '주요 지표' });
  expect(within(section).getByText(/2026.06 기준/)).toBeTruthy();
  expect(section.querySelector('time')?.dateTime).toBe(at);
  const calls = server.calls('GET', '/api/v1/companies/:id/metrics');
  expect(calls).toHaveLength(1);
  expect([...calls[0].query.keys()]).toEqual([]);
});
test.each([1200000, 0, null])(
  'D-COM-01 42 marketCap preserves %s',
  async (value) => {
    server.on('GET', '/api/v1/companies/:id/quote', () =>
      json({ ...quote, quote: { ...quote.quote, marketCap: value } }),
    );
    open();
    await screen.findByText('시가총액');
    expect(screen.getByText('시가총액').nextElementSibling?.textContent).toBe(
      value === null ? '미제공' : `${value.toLocaleString('ko-KR')}원`,
    );
  },
);
test('D-COM-01 42 handles unavailable and temporary metric errors independently', async () => {
  server.on('GET', '/api/v1/companies/:id/metrics', () =>
    apiError(503, 'SOURCE_UNAVAILABLE', '합성 장애'),
  );
  open();
  await screen.findByText('주요 지표를 불러오지 못했어요');
  server.on('GET', '/api/v1/companies/:id/metrics', () =>
    json({ status: 'unavailable', reason: '합성 지표 없음' }),
  );
  within(screen.getByRole('region', { name: '주요 지표' }))
    .getByRole('button', { name: '다시 시도' })
    .click();
  await screen.findByText('지표 미제공 · 합성 지표 없음');
  expect(screen.getByRole('heading', { name: company.name })).toBeTruthy();
});
test('D-COM-01 새5 waits for company and sends no section requests for a missing company', async () => {
  member();
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/companies/:id', () => pending.promise);
  open('&tab=documents&event=fixture-event');
  expect(server.calls('GET', '/api/v1/companies/:id/quote')).toHaveLength(0);
  await act(async () =>
    pending.resolve(apiError(404, 'RESOURCE_NOT_FOUND', '합성 없음')),
  );
  await screen.findByRole('heading', { name: '기업을 찾을 수 없어요' });
  expect(
    screen
      .getByRole('link', { name: '시장 전체 지도에서 찾기' })
      .getAttribute('href'),
  ).toBe('/?mode=all');
  expect(
    screen.getByRole('link', { name: '내 종목 보기' }).getAttribute('href'),
  ).toBe('/my');
  for (const path of [
    '/api/v1/companies/:id/quote',
    '/api/v1/companies/:id/prices',
    '/api/v1/companies/:id/metrics',
    '/api/v1/companies/:id/graph',
    '/api/v1/companies/:id/documents',
    '/api/v1/events',
    '/api/v1/events/:id',
    '/api/v1/companies/:id/issues/:issueId/impact',
    '/api/v1/portfolio',
    '/api/v1/me/settings',
  ])
    expect(server.calls('GET', path)).toHaveLength(0);
});
test.each([409, 422, 500])(
  'D-COM-01 새5 retains non-404 error %s and other independent sections',
  async (status) => {
    server.on('GET', '/api/v1/companies/:id', () =>
      apiError(
        status,
        status === 409
          ? 'VERSION_UNAVAILABLE'
          : status === 422
            ? 'INVALID_REQUEST'
            : 'INTERNAL_ERROR',
        '합성 오류',
      ),
    );
    open();
    await screen.findByText('PER');
    expect(
      screen.queryByRole('heading', { name: '기업을 찾을 수 없어요' }),
    ).toBeNull();
    expect(screen.getByText(/기업 정보 조회 실패/)).toBeTruthy();
  },
);
test('D-COM-01 46 preserves prototype disclaimer', async () => {
  open();
  await screen.findByRole('heading', { name: company.name });
  expect(
    screen.getByText('본 정보는 참고용이며 투자 권유가 아니에요.'),
  ).toBeTruthy();
});

test('D-COM-01 45 shares one settings request through automatic snapshot pinning', async () => {
  member();
  lists(true, true);
  const view = renderRoutes(
    [{ path: '/companies/:id', element: <CompanyDetailPage /> }],
    `/companies/${encodeURIComponent(id)}`,
  );
  await waitFor(() => expect(view.location()).toContain('graphVersion=v1'));
  await waitFor(() => expect(header().getByText('관심')).toBeTruthy());
  await screen.findByText('PER');
  expect(server.calls('GET', '/api/v1/me/settings')).toHaveLength(1);
  expect(server.calls('GET', '/api/v1/companies/:id/metrics')).toHaveLength(1);
});

test('D-COM-01 42 ignores late metrics after switching companies', async () => {
  const pending = deferred<Response>();
  const nextId = 'NASDAQ:FIXTURE';
  server.on('GET', '/api/v1/companies/:id/metrics', (r) =>
    r.params.id === id
      ? pending.promise
      : json({
          ...metrics,
          companyId: nextId,
          items: [
            { code: 'per', label: '다음 기업 PER', value: '7배', basis: null },
          ],
        }),
  );
  const view = renderRoutes(
    [{ path: '/companies/:id', element: <CompanyDetailPage /> }],
    `/companies/${encodeURIComponent(id)}?asOf=${encodeURIComponent(at)}&graphVersion=v1`,
  );
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/companies/:id/metrics')).toHaveLength(
      1,
    ),
  );
  await act(async () =>
    view.router.navigate(
      `/companies/${encodeURIComponent(nextId)}?asOf=${encodeURIComponent(at)}&graphVersion=v1`,
    ),
  );
  await screen.findByText('다음 기업 PER');
  await act(async () => pending.resolve(json(metrics)));
  expect(screen.queryByText('12.35배')).toBeNull();
  expect(screen.getByText('7배')).toBeTruthy();
});
