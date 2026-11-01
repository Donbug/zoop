import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import CompanyDetailPage from '@/pages/company/CompanyDetailPage';
import AppLayout from '@/components/common/AppLayout';
import MapPage from '@/pages/map/MapPage';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  bucketKey,
  impactEdges,
  money,
  requestTime,
  timeRange,
} from '@/components/company/detail-model';
import {
  createFakeServer,
  json,
  apiError,
  deferred,
} from './support/fakeServer';
import type { Event, Impact } from '@/types/company/detail';
import type { GraphResponse } from '@/types/map/graph';
import { renderRoutes } from './support/renderRoutes';
vi.mock('@/components/graph/GraphCanvas', () => ({
  default: ({ highlightedEdgeIds = [] }: { highlightedEdgeIds: string[] }) => (
    <output data-testid="map-highlight">{highlightedEdgeIds.join(',')}</output>
  ),
}));
const id = 'KRX:SYNTHETIC',
  time = '2026-10-06T03:00:00Z',
  old = '2026-10-05T03:00:00Z';
const metadata = {
  source: 'synthetic',
  asOf: time,
  graphVersion: 'v1',
  partial: false,
};
const source = {
  name: '합성 공급자',
  provider: 'synthetic',
  symbol: 'SYNTH',
  official: false,
  delayNote: '합성 지연',
  url: null,
};
const company = {
  id,
  name: '합성 기업',
  ticker: 'SYNTH',
  legalName: null,
  market: null,
  sector: null,
  representative: null,
  foundedDate: null,
  websiteUrl: null,
  directIssues: [],
  structuralIssues: [],
  summary: '합성 관계',
  metadata,
};
const events: Event[] = [
  {
    id: 'issue-a',
    title: '합성 사건 A',
    eventTime: old,
    timePrecision: 'datetime',
    reportedAt: old,
    relationTypes: ['INVOLVES'],
    companyIds: [id],
    articleCount: 1,
  },
  {
    id: 'issue-b',
    title: '합성 사건 B',
    eventTime: old,
    timePrecision: 'datetime',
    reportedAt: old,
    relationTypes: ['STRUCTURALLY_RELATED_TO'],
    companyIds: [id],
    articleCount: 2,
  },
];
const graph: GraphResponse = {
  nodes: [
    {
      id,
      kind: 'company',
      label: '합성 기업',
      isFocus: true,
      holding: false,
      watch: false,
      brandColor: null,
      logoUrl: null,
      eventTime: null,
      timePrecision: null,
      action: null,
      target: null,
      evidenceCount: null,
      geography: null,
    },
    {
      id: 'issue-a',
      kind: 'issue',
      label: '합성 사건 A',
      isFocus: false,
      holding: false,
      watch: false,
      brandColor: null,
      logoUrl: null,
      eventTime: old,
      timePrecision: 'datetime',
      action: null,
      target: null,
      evidenceCount: 1,
      geography: null,
    },
  ],
  edges: [
    {
      id: 'edge-a',
      source: 'issue-a',
      target: id,
      relationType: 'INVOLVES',
      role: null,
      summary: '합성 관계',
      assertionStatus: 'occurred',
      derived: false,
      via: [],
      evidenceIds: ['ev-a'],
    },
  ],
  metadata: {
    ...metadata,
    mode: 'all',
    truncated: false,
    emptyReason: null,
    focusCompanyIds: [id],
    depth: 1,
    limit: 100,
    requestId: 'synthetic',
    failures: [],
    personalFilter: null,
  },
};
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  useAuthStore.getState().clearSession();
  server = createFakeServer();
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: false,
      holdings: [],
      mockAsOf: null,
      valuation: null,
      metadata,
    }),
  );
  server.on('GET', '/api/v1/companies', () =>
    json({
      items: [{ id, name: '합성 기업', ticker: 'SYNTH' }],
      nextCursor: null,
    }),
  );
  server.on('GET', '/api/v1/companies/:id', (r) =>
    json({
      ...company,
      id: r.params.id,
      metadata: { ...metadata, asOf: r.query.get('asOf') ?? time },
    }),
  );
  server.on('GET', '/api/v1/companies/:id/quote', () =>
    json({
      status: 'available',
      companyId: id,
      source,
      quote: {
        price: 120,
        currency: 'KRW',
        asOf: time,
        change: 2,
        changeRate: 0.02,
        volume: null,
        dayLow: 100,
        dayHigh: 130,
        fiftyTwoWeekLow: null,
        fiftyTwoWeekHigh: null,
      },
    }),
  );
  server.on('GET', '/api/v1/companies/:id/prices', (r) =>
    json({
      status: 'available',
      companyId: id,
      period: r.query.get('period'),
      interval: { '1d': '5m', '1w': '1h', '1m': '1d', '1y': '1wk' }[
        r.query.get('period') ?? '1m'
      ],
      source,
      currency: 'KRW',
      points: [
        { time: old, open: 100, high: 115, low: 90, close: 110, volume: null },
        { time, open: 110, high: 130, low: 100, close: 120, volume: null },
      ].filter(
        (point) =>
          (!r.query.get('from') ||
            Date.parse(point.time) >= Date.parse(r.query.get('from')!)) &&
          (!r.query.get('to') ||
            Date.parse(point.time) <= Date.parse(r.query.get('to')!)),
      ),
    }),
  );
  server.on('GET', '/api/v1/events', (r) =>
    json({
      items: events,
      unknownTimeItems: [],
      nextCursor: null,
      metadata: {
        ...metadata,
        asOf: r.query.get('asOf') ?? time,
        total: 2,
        excludedUnknownTime: 0,
      },
    }),
  );
  server.on('GET', '/api/v1/events/:id', (r) =>
    json({
      ...events[0],
      id: r.params.id,
      period: null,
      companies: [
        {
          id,
          name: '합성 기업',
          role: null,
          roleUnconfirmed: true,
          relationType: 'INVOLVES',
        },
      ],
      articles: [],
      relations: [],
      evidenceIds: ['ev-a'],
      summary: { status: 'unavailable', reason: 'fixture summary unavailable' },
      mentions: [],
      sourceSupport: {
        articleCount: 0,
        knownLineageCount: null,
        unknownLineageArticles: [],
        independentSourceCount: null,
        duplicateGroups: [],
      },
      fieldDecisions: [],
      follows: { previous: [], next: [] },
      approval: null,
      metadata: {
        ...metadata,
        requestId: 'synthetic',
        failures: [],
        asOf: r.query.get('asOf') ?? time,
      },
    }),
  );
  server.on('GET', '/api/v1/companies/:id/graph', (r) =>
    json({
      ...graph,
      metadata: { ...graph.metadata, asOf: r.query.get('asOf') ?? time },
    }),
  );
  server.on('GET', '/api/v1/companies/:id/issues/:issueId/impact', (r) =>
    json({
      companyId: id,
      issueId: r.params.issueId,
      pathStatus: 'direct_available',
      steps: [
        {
          id: 'issue-a',
          kind: 'issue',
          reason: '실제 승인 관계',
          evidenceIds: ['ev-a'],
        },
        { id, kind: 'company', reason: '연결 기업', evidenceIds: ['ev-a'] },
      ],
      metadata: { ...metadata, asOf: r.query.get('asOf') ?? time },
    }),
  );
  server.on('GET', '/api/v1/companies/:id/financials', () =>
    json({
      status: 'unavailable',
      reason: '공급자 미연결',
      items: [],
      metadata,
    }),
  );
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({ items: [], nextCursor: null, metadata }),
  );
});
function Address() {
  const l = useLocation();
  return (
    <output data-testid="address">
      {l.pathname}
      {l.search}
    </output>
  );
}
function open(query = '') {
  return render(
    <MemoryRouter
      initialEntries={[`/companies/${encodeURIComponent(id)}${query}`]}
    >
      <Address />
      <Routes>
        <Route path="/companies/:id" element={<CompanyDetailPage />} />
        <Route path="/" element={<MapPage />} />
      </Routes>
    </MemoryRouter>,
  );
}
const pinned = `?asOf=${encodeURIComponent(time)}&graphVersion=v1`;

test('D-COM-01 48 normalizes a missing tab and announces the prototype notice', async () => {
  open(`${pinned}&tab=gone&depth=2`);
  await screen.findByText('요청한 탭이 없어 사건 탭을 보여 드려요');
  await waitFor(() =>
    expect(screen.getByTestId('address').textContent).not.toContain('tab=gone'),
  );
  expect(screen.getByTestId('address').textContent).toContain('depth=2');
});

test('D-COM-01 48 clears a missing event without changing pinned graph time', async () => {
  server.on('GET', '/api/v1/events/:id', () =>
    apiError(404, 'RESOURCE_NOT_FOUND'),
  );
  open(`${pinned}&event=gone&graphAsOf=${encodeURIComponent(old)}`);
  await screen.findByText('선택했던 사건을 지금은 볼 수 없어 선택을 풀었어요');
  await waitFor(() =>
    expect(screen.getByTestId('address').textContent).not.toContain(
      'event=gone',
    ),
  );
  const address = screen.getByTestId('address').textContent!;
  expect(address).not.toContain('event=gone');
  expect(
    new URL(address, 'http://localhost').searchParams.get('graphAsOf'),
  ).toBe(old);
});

test('D-COM-01 48 does not clear an event when the list fails', async () => {
  server.on('GET', '/api/v1/events', () => apiError(503, 'SOURCE_UNAVAILABLE'));
  open(`${pinned}&event=issue-a`);
  await screen.findByText(/타임라인 조회 실패/);
  expect(screen.getByTestId('address').textContent).toContain('event=issue-a');
});

test.each(['events', 'documents', 'info'])(
  'D-COM-01 F4 keeps one main and the skip-link target on the %s tab',
  async (tab) => {
    const view = renderRoutes(
      [
        {
          element: <AppLayout />,
          children: [
            { path: '/companies/:id', element: <CompanyDetailPage /> },
          ],
        },
      ],
      `/companies/${encodeURIComponent(id)}${pinned}&tab=${tab}`,
    );
    await screen.findByRole('heading', { name: '합성 기업', level: 1 });
    expect(screen.getAllByRole('main')).toHaveLength(1);
    const main = screen.getByRole('main');
    expect(main.id).toBe('service-main');
    // D-COM-01: 세 탭 모두 같은 지도 테마 표면 안에서 본문 랜드마크를 유지한다.
    expect(main.parentElement?.classList.contains('bg-zoop-page!')).toBe(true);
    const catalog = screen.getByRole('complementary', { name: '기업 선택' });
    expect(catalog.classList.contains('bg-zoop-surface')).toBe(true);
    expect(catalog.classList.contains('rounded-xl')).toBe(true);
    await view.user.click(
      screen.getByRole('link', { name: '본문으로 건너뛰기' }),
    );
    expect(document.activeElement).toBe(main);
    expect(view.router.state.location.hash).toBe('');
    expect(view.router.state.location.search).toContain(`tab=${tab}`);
  },
);

test.each(['/stocks', '/briefing'])(
  'D-COM-01 theme surface stays scoped away from %s',
  (path) => {
    renderRoutes(
      [
        {
          element: <AppLayout />,
          children: [{ path, element: <h1>합성 화면</h1> }],
        },
      ],
      path,
    );
    expect(
      screen
        .getByRole('main')
        .parentElement?.classList.contains('bg-zoop-page!'),
    ).toBe(false);
  },
);
function openHistory() {
  return renderRoutes(
    [
      {
        path: '/companies/:id',
        element: (
          <>
            <Address />
            <CompanyDetailPage />
          </>
        ),
      },
    ],
    `/companies/${encodeURIComponent(id)}${pinned}`,
  );
}

test('D-COM-06: Back and Forward restore event-time history after an outside selection', async () => {
  const { router, user } = openHistory();
  await user.click(
    await screen.findByRole('button', {
      name: '합성 사건 A · 이 당시 관계그래프 보기',
    }),
  );
  const past = `${router.state.location.pathname}${router.state.location.search}`;
  await user.click(screen.getByRole('button', { name: '합성 사건 B' }));
  await waitFor(() =>
    expect(screen.getByTestId('address').textContent).not.toContain(
      'graphAsOf',
    ),
  );
  const current = `${router.state.location.pathname}${router.state.location.search}`;
  for (let i = 0; i < 2; i++) {
    await act(async () => {
      await router.navigate(-1);
    });
    expect(
      screen.getByRole('button', { name: '현재 시점 관계 그래프로 돌아가기' }),
    ).toBeTruthy();
    expect(screen.getByTestId('address').textContent).toBe(past);
    await act(async () => {
      await router.navigate(1);
    });
    expect(
      screen.queryByRole('button', {
        name: '현재 시점 관계 그래프로 돌아가기',
      }),
    ).toBeNull();
    expect(screen.getByTestId('address').textContent).toBe(current);
  }
});

test('D-COM-06: closing outside without navigation still allows reopening the same event time', async () => {
  const { user } = openHistory();
  for (let i = 0; i < 2; i++) {
    await user.click(
      await screen.findByRole('button', {
        name: '합성 사건 A · 이 당시 관계그래프 보기',
      }),
    );
    expect(
      screen.getByRole('button', { name: '현재 시점 관계 그래프로 돌아가기' }),
    ).toBeTruthy();
    await user.click(screen.getByRole('region', { name: '기업 개요' }));
    await waitFor(() =>
      expect(screen.getByTestId('address').textContent).not.toContain(
        'graphAsOf',
      ),
    );
    expect(
      screen.queryByRole('button', {
        name: '현재 시점 관계 그래프로 돌아가기',
      }),
    ).toBeNull();
  }
});

test.each(['blank', 'selected'])(
  'D-COM-06: Back before delayed cleanup restores an earlier entry at the same timestamp (%s)',
  async (target) => {
    const { router, user } = openHistory();
    await user.click(
      await screen.findByRole('button', {
        name: '합성 사건 A · 이 당시 관계그래프 보기',
      }),
    );
    const past = screen.getByTestId('address').textContent;
    const panel = screen.getByRole('complementary', {
      name: '시점 기반 관계 그래프',
    });
    if (target === 'blank')
      await user.click(within(panel).getByRole('button', { name: '2단계' }));
    vi.useFakeTimers();
    try {
      fireEvent.click(
        target === 'blank'
          ? screen.getByRole('region', { name: '기업 개요' })
          : screen.getByRole('button', { name: '합성 사건 A' }),
      );
      await act(async () => {
        await router.navigate(-1);
      });
      expect(screen.getByTestId('address').textContent).toBe(past);
      expect(
        screen.getByRole('button', {
          name: '현재 시점 관계 그래프로 돌아가기',
        }),
      ).toBeTruthy();
      await act(async () => {
        vi.advanceTimersByTime(300);
      });
      expect(screen.getByTestId('address').textContent).toBe(past);
    } finally {
      vi.useRealTimers();
    }
  },
);

test('D-COM-06: catalog company switch clears the prior company event graph time', async () => {
  server.on('GET', '/api/v1/companies', () =>
    json({
      items: [{ id: 'KRX:OTHER', name: '리뷰 다른 기업', ticker: 'OTHER' }],
      nextCursor: null,
    }),
  );
  open(`${pinned}&graphAsOf=${encodeURIComponent(old)}`);
  const catalog = await screen.findByRole('complementary', {
    name: '기업 선택',
  });
  await userEvent.type(
    within(catalog).getByRole('textbox', { name: '기업명·종목 코드' }),
    'OTHER',
  );
  await userEvent.click(within(catalog).getByRole('button', { name: '검색' }));
  await userEvent.click(
    await within(catalog).findByRole('link', { name: /리뷰 다른 기업/ }),
  );
  const address = screen.getByTestId('address').textContent ?? '';
  expect(address).toContain('/companies/KRX%3AOTHER');
  expect(
    new URL(address, 'http://localhost').searchParams.has('graphAsOf'),
  ).toBe(false);
  expect(new URL(address, 'http://localhost').searchParams.get('asOf')).toBe(
    time,
  );
  expect(
    new URL(address, 'http://localhost').searchParams.get('graphVersion'),
  ).toBe('v1');
});

test.each([
  { eventTime: time, timePrecision: 'datetime' },
  { eventTime: null, timePrecision: 'unknown' },
  { eventTime: '2026-10', timePrecision: 'month' },
  { eventTime: '2026-10-06', timePrecision: 'day' },
])(
  'D-COM-06: selected issue map link overrides an older graph time (%j)',
  async (eventTime) => {
    server.on('GET', '/api/v1/events/:id', (r) =>
      json({
        ...events[0],
        id: r.params.id,
        ...eventTime,
        articles: [],
        relations: [],
        evidenceIds: [],
        metadata,
      }),
    );
    open(`${pinned}&graphAsOf=${encodeURIComponent(old)}&event=issue-a`);
    await screen.findByRole('heading', { name: '합성 사건 A' });
    const link = screen.getByRole('link', {
      name: '이 사건 시점의 관계를 지도에서 보기',
    });
    const href = new URL(link.getAttribute('href')!, 'http://localhost');
    expect(href.searchParams.get('asOf')).toBe(time);
    expect(href.searchParams.get('graphVersion')).toBe('v1');
    const graphLink = screen.getByRole('link', { name: '지도에서 보기' });
    const graphHref = new URL(
      graphLink.getAttribute('href')!,
      'http://localhost',
    );
    expect(graphHref.searchParams.get('asOf')).toBe(old);
    expect(graphHref.searchParams.has('graphVersion')).toBe(false);
  },
);

function VersionOnlyNavigation() {
  const navigate = useNavigate();
  return (
    <button
      onClick={() =>
        navigate(`/companies/${encodeURIComponent(id)}?graphVersion=v-past`)
      }
    >
      버전 단독 주소로 이동
    </button>
  );
}

test('D-COM-05: session response drives chart and timeline; 1d price request has no from', async () => {
  const range = {
    from: '2026-10-06T00:00:00Z',
    to: time,
    sessionDate: '2026-10-06',
  };
  server.on('GET', '/api/v1/companies/:id/prices', () =>
    json({
      status: 'available',
      companyId: id,
      period: '1d',
      interval: '5m',
      source,
      currency: 'KRW',
      range,
      points: [
        {
          time: range.from,
          open: 100,
          high: 100,
          low: 100,
          close: 100,
          volume: null,
        },
        { time, open: 120, high: 120, low: 120, close: 120, volume: null },
      ],
    }),
  );
  open(`${pinned}&period=1d`);
  await screen.findByText(
    '2026-10-06 장 · 거래소 현지 거래일 · 시간 표시는 KST',
  );
  await waitFor(() => {
    const request = server.calls('GET', '/api/v1/events').at(-1)!;
    expect(request.query.get('from')).toBe(range.from);
    expect(request.query.get('to')).toBe(range.to);
  });
  expect(
    server
      .calls('GET', '/api/v1/companies/:id/prices')
      .every((request) => !request.query.has('from')),
  ).toBe(true);
  expect(
    screen
      .getByRole('group', { name: '공급된 종가 차트' })
      .querySelector('polyline')
      ?.getAttribute('points'),
  ).toBe('10,160 530,20');
});

test('D-COM-03 shares the company request and restores the info tab after a map round trip', async () => {
  server.on('GET', '/api/v1/companies/:id', () =>
    json({ ...company, legalName: '합성 정식 법인명' }),
  );
  const query = `${pinned}&period=1w&tab=info&event=issue-a&bucket=2026-10-05`;
  open(query);
  const info = await screen.findByRole('region', { name: '기업 기준정보' });
  await within(info).findByText('합성 정식 법인명');
  expect(server.calls('GET', '/api/v1/companies/:id')).toHaveLength(1);
  await userEvent.click(screen.getByRole('link', { name: '지도에서 보기' }));
  await userEvent.click(
    await screen.findByRole('link', { name: '기업 상세로 돌아가기' }),
  );
  await screen.findByText('합성 정식 법인명');
  expect(screen.getByTestId('address').textContent).toBe(
    `/companies/${encodeURIComponent(id)}${query}`,
  );
});

test('direct URL defaults to one month and supplied timestamp/version; quote stays latest', async () => {
  open();
  await screen.findByRole('heading', { name: '합성 기업' });
  await screen.findByRole('group', { name: '공급된 종가 차트' });
  await waitFor(() =>
    expect(screen.getByTestId('address').textContent).toContain(
      'graphVersion=v1',
    ),
  );
  expect(
    server.calls('GET', '/api/v1/companies/:id/prices')[0].query.get('period'),
  ).toBe('1m');
  expect(
    server.calls('GET', '/api/v1/companies/:id/quote')[0].query.has('asOf'),
  ).toBe(false);
  expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(0);
});
test('same bucket exposes count then individual cards; selecting an issue keeps the reference time', async () => {
  open(pinned);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '2026-10-05 · 사건 2건' }),
  );
  await user.click(screen.getByRole('button', { name: '합성 사건 A' }));
  await screen.findByRole('heading', { name: '합성 사건 A' });
  expect(screen.getByTestId('address').textContent).toContain('event=issue-a');
  // 사건을 골라도 기준 시점은 그대로다. 그래프 시점은 [이 당시 관계그래프 보기]로만 옮긴다.
  expect(screen.getByTestId('address').textContent).toContain(
    `asOf=${encodeURIComponent(time)}`,
  );
  await waitFor(() =>
    expect(
      server
        .calls('GET', '/api/v1/companies/:id/graph')
        .at(-1)
        ?.query.get('asOf'),
    ).toBe(time),
  );
});
test('FS044: changing the period keeps the selected issue and moves it to the new bucket', async () => {
  open(pinned);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '2026-10-05 · 사건 2건' }),
  );
  await user.click(screen.getByRole('button', { name: '합성 사건 A' }));
  await screen.findByRole('heading', { name: '합성 사건 A' });
  await user.click(screen.getByRole('button', { name: '1주' }));
  const address = new URLSearchParams(
    screen.getByTestId('address').textContent!.split('?')[1],
  );
  expect(address.get('period')).toBe('1w');
  expect(address.get('event')).toBe('issue-a');
  expect(address.get('bucket')).toBeTruthy();
  expect(address.get('bucket')).not.toBe('2026-10-05');
  expect(
    await screen.findByRole('button', { name: '합성 사건 A' }),
  ).toBeTruthy();
});
test('price bars are not selectable; period change retains snapshot and changes resolution', async () => {
  open(pinned);
  const user = userEvent.setup();
  await screen.findByRole('group', { name: '공급된 종가 차트' });
  // D-COM-06 시점 이동을 두지 않으므로 가격 봉 선택 버튼이 없다.
  expect(screen.queryByRole('button', { name: `차트 ${old} 선택` })).toBeNull();
  await user.click(screen.getByRole('button', { name: '1주' }));
  await waitFor(() =>
    expect(
      server
        .calls('GET', '/api/v1/companies/:id/prices')
        .at(-1)
        ?.query.get('period'),
    ).toBe('1w'),
  );
  expect(screen.getByTestId('address').textContent).toContain(
    'graphVersion=v1',
  );
});
test('market unavailability and provider errors remain independent with retry', async () => {
  server.on('GET', '/api/v1/companies/:id/quote', () =>
    apiError(503, 'SOURCE_UNAVAILABLE'),
  );
  open(pinned);
  await screen.findByText(/시세 조회 실패/);
  expect(
    await screen.findByRole('group', { name: '공급된 종가 차트' }),
  ).toBeTruthy();
  server.on('GET', '/api/v1/companies/:id/quote', () =>
    json({ status: 'unavailable', reason: '종목 미지원' }),
  );
  await userEvent.click(screen.getByRole('button', { name: '시세 다시 조회' }));
  await screen.findByText('시세 미제공 · 종목 미지원');
});
test('connected member displays mock holding without replacing null values', async () => {
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: {
      id: 'synthetic-member',
      email: 'synthetic@example.test',
      displayName: '가상',
    },
    setup: { completed: true, tutorialCompleted: false },
    csrfToken: 'synthetic',
    expiresAt: null,
  });
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      holdings: [
        {
          companyId: id,
          quantity: 20,
          avgPrice: 100,
          avgPriceCurrency: 'KRW',
          marketValue: null,
          weight: null,
          quote: { status: 'unavailable' },
        },
      ],
      mockAsOf: old,
      valuation: { calculatedAt: time, weightUnavailableReason: '시세 미제공' },
      metadata,
    }),
  );
  open(pinned);
  await screen.findByText('20주');
  expect(screen.getByText('-', { selector: 'dd' })).toBeTruthy();
  // D-COM-01 N-x: same currency format as the price; null stays '미제공'.
  expect(screen.getByText('100원', { selector: 'dd' })).toBeTruthy();
  expect(screen.getByText('시세 미제공', { selector: 'dd' })).toBeTruthy();
  expect(screen.getByText('100원 ~ 130원', { selector: 'dd' })).toBeTruthy();
  expect(screen.getByText('미제공 ~ 미제공', { selector: 'dd' })).toBeTruthy();
  const region = screen.getByRole('region', { name: '가상 계좌 보유' });
  expect(within(region).getAllByText(/모의/).length).toBeGreaterThan(0);
  // D-COM-01 / F6: private valuation timestamps retain the original machine values.
  expect(
    within(region)
      .getByText('2026-10-05 12:00 KST', { exact: true })
      .getAttribute('datetime'),
  ).toBe(old);
  expect(
    within(region)
      .getAllByText('2026-10-06 12:00 KST', { exact: true })
      .every((element) => element.getAttribute('datetime') === time),
  ).toBe(true);
  await act(async () => useAuthStore.getState().clearSession());
  expect(screen.queryByText('20주')).toBeNull();
});
test('D-COM-01 company detail hides holdings when the portfolio only holds other companies', async () => {
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: {
      id: 'synthetic-member',
      email: 'synthetic@example.test',
      displayName: '가상',
    },
    setup: { completed: true, tutorialCompleted: false },
    csrfToken: 'synthetic',
    expiresAt: null,
  });
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      holdings: [
        {
          companyId: 'KRX:OTHER',
          quantity: 20,
          avgPrice: 100,
          avgPriceCurrency: 'KRW',
          marketValue: 2000,
          weight: 1,
          quote: { status: 'available', currency: 'KRW' },
        },
      ],
      mockAsOf: old,
      valuation: null,
      metadata,
    }),
  );
  open(pinned);
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/portfolio').length).toBeGreaterThan(0),
  );
  expect(screen.queryByRole('region', { name: '가상 계좌 보유' })).toBeNull();
  expect(screen.queryByText('이 기업의 모의 보유 종목이 없어요.')).toBeNull();
});
test('switching member hides previous holdings while next response is pending', async () => {
  const session = (id: string) => ({
    authenticated: true as const,
    kind: 'member' as const,
    user: { id, email: 'synthetic@example.test', displayName: '가상' },
    setup: { completed: true, tutorialCompleted: false },
    csrfToken: 'synthetic',
    expiresAt: null,
  });
  useAuthStore.getState().setSession(session('a'));
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      holdings: [
        {
          companyId: id,
          quantity: 777,
          avgPrice: 100,
          avgPriceCurrency: null,
          marketValue: null,
          weight: null,
          quote: { status: 'unavailable' },
        },
      ],
      mockAsOf: old,
      valuation: null,
      metadata,
    }),
  );
  open(pinned);
  await screen.findByText('777주');
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/portfolio', () => pending.promise);
  await act(async () => useAuthStore.getState().setSession(session('b')));
  expect(screen.queryByText('777주')).toBeNull();
  await act(async () =>
    pending.resolve(
      json({
        connected: false,
        holdings: [],
        mockAsOf: null,
        valuation: null,
        metadata,
      }),
    ),
  );
  expect(screen.queryByRole('region', { name: '가상 계좌 보유' })).toBeNull();
});
test('event map link opens the event-time map; round trip restores period, time, tab, event and bucket exactly', async () => {
  const query = `${pinned}&period=1m&tab=events&event=issue-a&bucket=2026-10-05`;
  open(query);
  await screen.findByRole('heading', { name: '합성 사건 A' });
  await userEvent.click(
    screen.getByRole('link', { name: '이 사건 시점의 관계를 지도에서 보기' }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('map-highlight').textContent).toBe('edge-a'),
  );
  // 지도는 사건 시각 기준으로 열고, 그 시점의 공개 버전은 서버가 고른다.
  const mapGraph = server.calls('GET', '/api/v1/companies/:id/graph').at(-1);
  expect(mapGraph?.query.get('asOf')).toBe(old);
  expect(mapGraph?.query.get('graphVersion')).toBeNull();
  await userEvent.click(
    screen.getByRole('link', { name: '기업 상세로 돌아가기' }),
  );
  expect(screen.getByTestId('address').textContent).toBe(
    `/companies/${encodeURIComponent(id)}${query}`,
  );
});
test('FS044 · D-COM-06 / M-COM-02: unavailable event-time graph keeps return route without futile impact retry', async () => {
  server.on('GET', '/api/v1/companies/:id/issues/:issueId/impact', () =>
    apiError(409, 'VERSION_UNAVAILABLE'),
  );
  const query = `${pinned}&period=1m&tab=events&event=issue-a&bucket=2026-10-05`;
  open(query);
  await screen.findByRole('heading', { name: '합성 사건 A' });
  await userEvent.click(
    screen.getByRole('link', { name: '이 사건 시점의 관계를 지도에서 보기' }),
  );
  await screen.findByText(/사건 시점의 그래프 버전을 사용할 수 없어요/);
  expect(
    screen.queryByRole('button', { name: '영향 경로 다시 조회' }),
  ).toBeNull();
  await userEvent.click(
    screen.getByRole('link', { name: '기업 상세로 돌아가기' }),
  );
  expect(screen.getByTestId('address').textContent).toBe(
    `/companies/${encodeURIComponent(id)}${query}`,
  );
});
test('documents and company profile preserve absence and refuse unsafe external links', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({
      items: [
        {
          id: 'doc',
          title: '합성 뉴스',
          publisher: null,
          publishedAt: null,
          url: 'javascript:alert(1)',
        },
      ],
      nextCursor: null,
      metadata,
    }),
  );
  open(pinned);
  await userEvent.click(screen.getByRole('button', { name: '문서' }));
  await screen.findByRole('heading', { name: '합성 뉴스' });
  expect(screen.queryByRole('link', { name: '원문 보기' })).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: '기업 정보' }));
  await screen.findByRole('heading', { name: '기업 기준정보' });
  expect(screen.queryByRole('link', { name: '공식 웹사이트' })).toBeNull();
});
test('coarse date issue does not fabricate midnight or shift reference time', async () => {
  server.on('GET', '/api/v1/events', () =>
    json({
      items: [{ ...events[0], timePrecision: 'day', eventTime: '2026-10-05' }],
      unknownTimeItems: [],
      nextCursor: null,
      metadata: { ...metadata, total: 1, excludedUnknownTime: 0 },
    }),
  );
  open(pinned);
  await userEvent.click(
    await screen.findByRole('button', { name: '2026-10-05 · 사건 1건' }),
  );
  await userEvent.click(screen.getByRole('button', { name: '합성 사건 A' }));
  expect(screen.getByTestId('address').textContent).toContain(
    `asOf=${encodeURIComponent(time)}`,
  );
});
test('events fetch all cursor pages with matching snapshots', async () => {
  server.on('GET', '/api/v1/events', (r) =>
    json({
      items: r.query.has('cursor') ? [events[1]] : [events[0]],
      unknownTimeItems: [],
      nextCursor: r.query.has('cursor') ? null : 'page2',
      metadata: { ...metadata, total: 2, excludedUnknownTime: 0 },
    }),
  );
  open(pinned);
  await screen.findByRole('button', { name: '2026-10-05 · 사건 2건' });
  expect(server.calls('GET', '/api/v1/events')).toHaveLength(2);
});
test('snapshot changes between event pages fail rather than mix versions', async () => {
  server.on('GET', '/api/v1/events', (r) =>
    json({
      items: [events[0]],
      unknownTimeItems: [],
      nextCursor: r.query.has('cursor') ? null : 'page2',
      metadata: {
        ...metadata,
        graphVersion: r.query.has('cursor') ? 'v2' : 'v1',
        total: 2,
        excludedUnknownTime: 0,
      },
    }),
  );
  open(pinned);
  await screen.findByText(/조회 중 공개 자료 기준이 바뀌었어요/);
  expect(screen.queryByRole('button', { name: /사건 2건/ })).toBeNull();
});
test('unsupported resolution is not mislabeled as requested chart', async () => {
  server.on('GET', '/api/v1/companies/:id/prices', () =>
    json({
      status: 'available',
      companyId: id,
      period: '1m',
      interval: '5m',
      source,
      currency: 'KRW',
      points: [],
    }),
  );
  open(pinned);
  await screen.findByText(/공급된 봉 해상도가 달라/);
  expect(screen.queryByRole('group', { name: '공급된 종가 차트' })).toBeNull();
});
test('buckets follow exact five-minute/hour/day/week resolutions and never invented impact', () => {
  expect(
    bucketKey({ ...events[0], eventTime: '2026-10-05T03:02:00Z' }, '1d'),
  ).toBe(bucketKey({ ...events[0], eventTime: '2026-10-05T03:04:00Z' }, '1d'));
  expect(bucketKey(events[0], '1y')).toContain('주');
  expect(timeRange(time, '1w').from).toBe('2026-09-29T03:00:00.000Z');
  const impact: Impact = {
    companyId: id,
    issueId: 'issue-a',
    pathStatus: 'direct_available',
    steps: [
      {
        id: 'issue-a',
        kind: 'issue',
        reason: 'confirmed',
        evidenceIds: ['ev-a'],
      },
      { id, kind: 'company', reason: 'confirmed', evidenceIds: ['ev-a'] },
    ],
    metadata,
  };
  expect(impactEdges(graph, impact)).toEqual(['edge-a']);
  expect(
    impactEdges(
      {
        ...graph,
        edges: graph.edges.map((edge) => ({
          ...edge,
          relationType: 'STRUCTURALLY_RELATED_TO',
          assertionStatus: null,
        })),
      },
      { ...impact, pathStatus: 'structural_path_details_unavailable' },
    ),
  ).toEqual([]);
  expect(
    impactEdges(graph, {
      ...impact,
      steps: impact.steps.map((step) => ({ ...step, evidenceIds: [] })),
    }),
  ).toEqual([]);
  expect(
    impactEdges(graph, {
      ...impact,
      metadata: { ...metadata, graphVersion: 'v2' },
    }),
  ).toEqual([]);
  expect(
    impactEdges(
      { ...graph, edges: graph.edges.map((e) => ({ ...e, derived: true })) },
      impact,
    ),
  ).toEqual([]);
});

test('calendar ranges clamp month ends and leap days without future fallback', () => {
  expect(timeRange('2026-03-31T03:00:00Z', '1m').from).toBe(
    '2026-02-28T03:00:00.000Z',
  );
  expect(timeRange('2024-02-29T03:00:00Z', '1y').from).toBe(
    '2023-02-28T03:00:00.000Z',
  );
});
test('selected graph version is not silently replaced with latest', async () => {
  server.on('GET', '/api/v1/companies/:id/graph', () =>
    json({ ...graph, metadata: { ...graph.metadata, graphVersion: 'v2' } }),
  );
  open(pinned);
  await screen.findByText(/요청한 공개 버전과 다른 자료를 받았어요/);
  expect(
    screen.queryByRole('img', { name: '기준 시점 기업 관계 그래프' }),
  ).toBeNull();
});

test('FS043: event card enters its document scope with period and reference time retained', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', (r) =>
    json({
      items: [
        {
          id: 'doc-synthetic',
          title: '사건 A 근거 문서',
          publisher: '합성 출처',
          publishedAt: old,
          url: null,
          kind: 'news',
          events: [
            {
              eventId: 'issue-a',
              title: '합성 사건 A',
              relationType: 'REPORTS',
            },
          ],
          quotes: [],
          sentiment: null,
        },
      ],
      nextCursor: null,
      metadata: { ...metadata, asOf: r.query.get('asOf') ?? time },
    }),
  );
  open(pinned);
  await userEvent.click(
    await screen.findByRole('button', { name: '2026-10-05 · 사건 2건' }),
  );
  await userEvent.click(
    screen.getByRole('button', { name: '근거 문서 1건 보기' }),
  );
  await screen.findByRole('heading', { name: '사건 A 근거 문서' });
  expect(screen.getByTestId('address').textContent).toContain('tab=documents');
  expect(screen.getByTestId('address').textContent).toContain('docScope=event');
  expect(screen.getByTestId('address').textContent).toContain('event=issue-a');
  expect(
    server
      .calls('GET', '/api/v1/companies/:id/documents')
      .at(-1)
      ?.query.get('asOf'),
  ).toBe(time);
});

test('D-COM-04 depth change retains company period/time/tab and passes exact scope to the API', async () => {
  server.on('GET', '/api/v1/companies/:id/graph', (request) =>
    json({
      ...graph,
      metadata: {
        ...graph.metadata,
        depth: Number(request.query.get('depth')),
        asOf: request.query.get('asOf'),
      },
    }),
  );
  open(`${pinned}&period=1m&tab=info`);
  const preview = await screen.findByRole('img', {
    name: '기준 시점 기업 관계 그래프',
  });
  const original = preview.getAttribute('viewBox');
  await userEvent.click(
    screen.getByRole('button', { name: '기업 관계 그래프 확대' }),
  );
  expect(preview.getAttribute('viewBox')).not.toBe(original);
  await userEvent.click(screen.getByRole('button', { name: '2단계' }));
  await waitFor(() =>
    expect(
      server
        .calls('GET', '/api/v1/companies/:id/graph')
        .at(-1)
        ?.query.get('depth'),
    ).toBe('2'),
  );
  const address = screen.getByTestId('address').textContent;
  expect(address).toContain('tab=info');
  expect(address).toContain('period=1m');
  expect(address).toContain('graphVersion=v1');
  await waitFor(() =>
    expect(
      screen
        .getByRole('img', { name: '기준 시점 기업 관계 그래프' })
        .getAttribute('viewBox'),
    ).toBe(original),
  );
});

test('graph issue selection clears previous document/evidence while retaining tab and reference time', async () => {
  open(
    `${pinned}&period=1w&tab=documents&event=issue-b&document=old-document&evidence=old-evidence&bucket=old-bucket`,
  );
  const region = screen.getByRole('complementary', {
    name: '시점 기반 관계 그래프',
  });
  await within(region).findByRole('button', { name: '사건 · 합성 사건 A' });
  await userEvent.click(
    within(region).getByRole('button', { name: '기업 관계 그래프 확대' }),
  );
  const view = within(region).getByRole('img').getAttribute('viewBox');
  await userEvent.click(
    await within(region).findByRole('button', { name: '사건 · 합성 사건 A' }),
  );
  const address = screen.getByTestId('address').textContent;
  expect(address).toContain('event=issue-a');
  expect(address).toContain('tab=documents');
  expect(address).toContain('period=1w');
  expect(address).not.toContain('document=');
  expect(address).not.toContain('evidence=');
  expect(address).toContain('bucket=2026-10-05T03%3A00%3A00.000Z');
  expect(within(region).getByRole('img').getAttribute('viewBox')).toBe(view);
});

test('D-COM-04 version, missing and outage failures are told apart; only outages offer retry', async () => {
  let failure = apiError(409, 'VERSION_UNAVAILABLE');
  server.on('GET', '/api/v1/companies/:id/graph', () => failure);
  const view = open(pinned);
  const region = () =>
    screen.getByRole('complementary', { name: '시점 기반 관계 그래프' });
  await within(region()).findByText(/이 기준 시점의 공개 자료가 없어요/);
  expect(
    within(region()).queryByRole('button', { name: '관계 그래프 다시 조회' }),
  ).toBeNull();
  view.unmount();

  failure = apiError(404, 'RESOURCE_NOT_FOUND');
  const missing = open(pinned);
  await within(region()).findByText(/해당 자료가 없어요/);
  expect(
    within(region()).queryByRole('button', { name: '관계 그래프 다시 조회' }),
  ).toBeNull();
  missing.unmount();

  failure = apiError(503, 'SOURCE_UNAVAILABLE');
  open(pinned);
  expect(
    await within(region()).findByRole('button', {
      name: '관계 그래프 다시 조회',
    }),
  ).toBeTruthy();
  expect(within(region()).queryByRole('img')).toBeNull();
});

test('FS044 edges without published evidence are excluded from actual impact paths', () => {
  const impact: Impact = {
    companyId: id,
    issueId: 'issue-a',
    pathStatus: 'direct_available',
    steps: [
      {
        id: 'issue-a',
        kind: 'issue',
        reason: '합성 근거',
        evidenceIds: ['ev-a'],
      },
      { id, kind: 'company', reason: '합성 근거', evidenceIds: ['ev-a'] },
    ],
    metadata,
  };
  expect(
    impactEdges(
      {
        ...graph,
        edges: graph.edges.map((edge) => ({
          ...edge,
          evidenceIds: [],
        })),
      },
      impact,
    ),
  ).toEqual([]);
});

test('D-COM-05/06: periods preserve graph context; legacy 1d omits price from only', async () => {
  open(pinned);
  for (const [period, label, bucket] of [
    ['1m', '1개월', '일'],
    ['1d', '1일', '5분'],
    ['1w', '1주', '1시간'],
    ['1y', '1년', '주'],
  ]) {
    await userEvent.click(screen.getByRole('button', { name: label }));
    await waitFor(() =>
      expect(
        server
          .calls('GET', '/api/v1/companies/:id/prices')
          .at(-1)
          ?.query.get('period'),
      ).toBe(period),
    );
    await screen.findByRole('group', { name: '공급된 종가 차트' });
    const pricesRequest = server
      .calls('GET', '/api/v1/companies/:id/prices')
      .at(-1)!;
    const eventsRequest = server.calls('GET', '/api/v1/events').at(-1)!;
    if (period === '1d') {
      expect(pricesRequest.query.has('from')).toBe(false);
      expect(eventsRequest.query.get('from')).toBe('2026-10-05T03:00:00.000Z');
    } else {
      expect(pricesRequest.query.get('from')).toBe(
        eventsRequest.query.get('from'),
      );
    }
    expect(pricesRequest.query.get('to')).toBe(eventsRequest.query.get('to'));
    expect(eventsRequest.query.get('asOf')).toBe(time);
    expect(eventsRequest.query.get('graphVersion')).toBe('v1');
    expect(screen.getByText(new RegExp(`· ${bucket} 버킷`))).toBeTruthy();
  }
});

test('chart count marker expands both events without changing public cutoff; event synchronizes graph', async () => {
  open(pinned);
  await userEvent.click(
    await screen.findByRole('button', {
      name: '차트 사건 2026-10-05 · 사건 2건',
    }),
  );
  expect(screen.getByRole('button', { name: '합성 사건 A' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '합성 사건 B' })).toBeTruthy();
  expect(screen.getByTestId('address').textContent).toContain(
    `asOf=${encodeURIComponent(time)}`,
  );
  await userEvent.click(screen.getByRole('button', { name: '합성 사건 A' }));
  await screen.findByRole('heading', { name: '합성 사건 A' });
  expect(
    screen
      .getByRole('button', { name: '차트 사건 2026-10-05 · 사건 2건' })
      .getAttribute('aria-pressed'),
  ).toBe('true');
  expect(screen.getByTestId('address').textContent).toContain(
    `asOf=${encodeURIComponent(time)}`,
  );
  const region = screen.getByRole('complementary', {
    name: '시점 기반 관계 그래프',
  });
  expect(
    within(region)
      .getByRole('button', { name: '사건 · 합성 사건 A' })
      .getAttribute('aria-pressed'),
  ).toBe('true');
});

test('late timeline response from the former period is discarded after a period change', async () => {
  const pending = deferred<Response>();
  let first = true;
  server.on('GET', '/api/v1/events', () => {
    if (first) {
      first = false;
      return pending.promise;
    }
    return json({
      items: [events[0]],
      unknownTimeItems: [],
      nextCursor: null,
      metadata: {
        ...metadata,
        total: 1,
        excludedUnknownTime: 0,
      },
    });
  });
  open(pinned);
  await userEvent.click(await screen.findByRole('button', { name: '1주' }));
  await screen.findAllByRole('button', { name: /· 사건 1건$/ });
  await act(async () =>
    pending.resolve(
      json({
        items: events,
        unknownTimeItems: [],
        nextCursor: null,
        metadata: { ...metadata, total: 2, excludedUnknownTime: 0 },
      }),
    ),
  );
  expect(screen.queryAllByRole('button', { name: /· 사건 2건$/ })).toHaveLength(
    0,
  );
  expect(
    screen.getAllByRole('button', { name: /· 사건 1건$/ })[0],
  ).toBeTruthy();
});

test('timeline version failure and partial retry states preserve historical URL', async () => {
  server.on('GET', '/api/v1/events', () =>
    apiError(409, 'VERSION_UNAVAILABLE'),
  );
  const view = open(pinned);
  await screen.findByText(/이 기준 시점의 공개 자료가 없어요/);
  expect(
    screen.queryByRole('button', { name: '타임라인 다시 조회' }),
  ).toBeNull();
  view.unmount();
  server.on('GET', '/api/v1/events', () =>
    json({
      items: events,
      unknownTimeItems: [],
      nextCursor: null,
      metadata: {
        ...metadata,
        total: 2,
        excludedUnknownTime: 0,
        partial: true,
        failures: [
          {
            section: 'events',
            code: 'SOURCE_UNAVAILABLE',
            message: '합성 부분 장애',
          },
        ],
      },
    }),
  );
  open(pinned);
  await screen.findByText('합성 부분 장애');
  await userEvent.click(
    screen.getByRole('button', { name: '타임라인 다시 조회' }),
  );
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/events')).toHaveLength(3),
  );
  expect(
    server.calls('GET', '/api/v1/events').at(-1)?.query.get('graphVersion'),
  ).toBe('v1');
  expect(screen.getByTestId('address').textContent).toContain(
    `asOf=${encodeURIComponent(time)}`,
  );
});

test('different issue or company impact cannot highlight the selected event', async () => {
  server.on('GET', '/api/v1/companies/:id/issues/:issueId/impact', () =>
    json({
      companyId: 'wrong-company',
      issueId: 'wrong-event',
      steps: [],
      metadata,
    }),
  );
  open(`${pinned}&event=issue-a`);
  await screen.findByText(/요청한 기업·사건과 다른 영향 경로/);
});

test('mismatched chart company/period is rejected rather than shown as selected series', async () => {
  server.on('GET', '/api/v1/companies/:id/prices', () =>
    json({
      status: 'available',
      companyId: 'wrong',
      period: '1y',
      interval: '1d',
      points: [],
      source,
      currency: 'KRW',
    }),
  );
  open(pinned);
  await screen.findByText(/요청한 기업·기간과 다른 차트/);
  expect(screen.queryByRole('group', { name: '공급된 종가 차트' })).toBeNull();
});

test('chart bucket marker opens event cards from the info tab without altering cutoff', async () => {
  open(`${pinned}&tab=info`);
  await userEvent.click(
    await screen.findByRole('button', {
      name: '차트 사건 2026-10-05 · 사건 2건',
    }),
  );
  expect(screen.getByTestId('address').textContent).toContain('tab=events');
  expect(screen.getByTestId('address').textContent).toContain(
    `asOf=${encodeURIComponent(time)}`,
  );
  expect(screen.getByRole('button', { name: '합성 사건 B' })).toBeTruthy();
});

test('selected graph version rejects a response that omits snapshot metadata', async () => {
  server.on('GET', '/api/v1/companies/:id/graph', () => {
    const withoutMetadata: Partial<GraphResponse> = { ...graph };
    delete withoutMetadata.metadata;
    return json(withoutMetadata);
  });
  open(pinned);
  await screen.findByText(/요청한 공개 버전과 다른 자료를 받았어요/);
  expect(
    screen.queryByRole('img', { name: '기준 시점 기업 관계 그래프' }),
  ).toBeNull();
});

test('FS040 calendar ranges clamp month and leap year at the Korean midnight boundary', () => {
  expect(timeRange('2026-03-31T00:00:00+09:00', '1m')).toEqual({
    from: '2026-02-27T15:00:00.000Z',
    to: '2026-03-30T15:00:00.000Z',
  });
  expect(timeRange('2024-02-29T00:00:00+09:00', '1y').from).toBe(
    '2023-02-27T15:00:00.000Z',
  );
  expect(timeRange('2026-03-30T15:00:00Z', '1m')).toEqual(
    timeRange('2026-03-31T00:00:00+09:00', '1m'),
  );
});

test('timeline shows the latest ten day buckets first and loads older ones on demand', async () => {
  const many = Array.from({ length: 12 }, (_, i) => ({
    ...events[0],
    id: `issue-day-${i}`,
    title: `합성 날짜 사건 ${i}`,
    eventTime: new Date(Date.parse(time) - (i + 1) * 86400000).toISOString(),
  }));
  server.on('GET', '/api/v1/events', (r) =>
    json({
      items: many,
      unknownTimeItems: [],
      nextCursor: null,
      metadata: {
        ...metadata,
        asOf: r.query.get('asOf') ?? time,
        total: many.length,
        excludedUnknownTime: 0,
      },
    }),
  );
  open(`${pinned}&period=1m&tab=events`);
  const timeline = await screen.findByRole('region', { name: '사건 타임라인' });
  await within(timeline).findByRole('button', { name: '합성 날짜 사건 0' });
  expect(
    within(timeline).queryByRole('button', { name: '합성 날짜 사건 11' }),
  ).toBeNull();
  await userEvent.click(
    within(timeline).getByRole('button', { name: /이전 사건 더 보기/ }),
  );
  expect(
    within(timeline).getByRole('button', { name: '합성 날짜 사건 11' }),
  ).toBeTruthy();
  expect(
    within(timeline).queryByRole('button', { name: /이전 사건 더 보기/ }),
  ).toBeNull();
});

test('A02: timeline shows relation types in Korean and empty relations as unconfirmed', async () => {
  server.on('GET', '/api/v1/events', (r) =>
    json({
      items: [
        ...events,
        {
          ...events[0],
          id: 'issue-c',
          title: '합성 사건 C',
          relationTypes: [],
        },
      ],
      unknownTimeItems: [],
      nextCursor: null,
      metadata: {
        ...metadata,
        asOf: r.query.get('asOf') ?? time,
        total: 3,
        excludedUnknownTime: 0,
      },
    }),
  );
  open(`${pinned}&period=1m&tab=events`);
  const timeline = await screen.findByRole('region', { name: '사건 타임라인' });
  await within(timeline).findByRole('button', { name: '합성 사건 C' });
  expect(within(timeline).getByText(/문서 1건 · 직접 관련$/)).toBeTruthy();
  expect(within(timeline).getByText(/문서 2건 · 구조적 관련$/)).toBeTruthy();
  expect(within(timeline).getByText(/직접 관계 미확인$/)).toBeTruthy();
  expect(
    within(timeline).queryByText(/INVOLVES|STRUCTURALLY_RELATED_TO/),
  ).toBeNull();
});

test('F05: quote outages offer retry only when the server says it may help', async () => {
  let retryable = false;
  server.on('GET', '/api/v1/companies/:id/quote', () =>
    json(
      {
        error: {
          code: 'SOURCE_UNAVAILABLE',
          message: '시세 공급자 장애',
          retryable,
        },
      },
      503,
    ),
  );
  const view = open(pinned);
  const quoteRegion = () => screen.getByRole('region', { name: '최신 시세' });
  await within(quoteRegion()).findByText(
    /자료 공급원의 설정이나 응답 형식 문제/,
  );
  expect(
    within(quoteRegion()).queryByRole('button', { name: '시세 다시 조회' }),
  ).toBeNull();
  view.unmount();

  retryable = true;
  open(pinned);
  expect(
    await within(quoteRegion()).findByRole('button', {
      name: '시세 다시 조회',
    }),
  ).toBeTruthy();
});

test('without a published graph version the page does not pin a reference time (no 409 loop)', async () => {
  server.on('GET', '/api/v1/companies/:id', (r) =>
    json({
      ...company,
      id: r.params.id,
      directIssues: [],
      structuralIssues: [],
      metadata: {
        ...metadata,
        graphVersion: null,
        partial: true,
        asOf: time,
      },
    }),
  );
  open();
  await screen.findByRole('heading', { name: '합성 기업' });
  await new Promise((resolve) => setTimeout(resolve, 50));
  const address = screen.getByTestId('address').textContent!;
  expect(address).not.toContain('asOf=');
  expect(address).not.toContain('graphVersion=');
  expect(
    server
      .calls('GET', '/api/v1/companies/:id')
      .every((call) => !call.query.has('asOf')),
  ).toBe(true);
});

test('price bar times without seconds become RFC 3339 request times for asOf', () => {
  // Toss bars arrive as 2026-10-20T00:00+09:00; company and graph APIs reject that (422).
  expect(requestTime('2026-10-20T00:00+09:00')).toBe('2026-10-19T15:00:00Z');
  expect(requestTime('2026-10-20T17:40+09:00')).toBe('2026-10-20T08:40:00Z');
  expect(requestTime('2026-10-20T06:03:38.413Z')).toBe(
    '2026-10-20T06:03:38.413Z',
  );
});

test('first entry pins the company reference time and version, not an older last price bar (closed market)', async () => {
  // FS040: on a weekend the last bar is Friday; the latest public version activated afterwards.
  const saturday = '2026-10-24T03:00:00Z';
  server.on('GET', '/api/v1/companies/:id', (r) =>
    json({
      ...company,
      id: r.params.id,
      metadata: {
        ...metadata,
        asOf: r.query.get('asOf') ?? saturday,
        graphVersion: 'v-weekend',
      },
    }),
  );
  open();
  await screen.findByRole('heading', { name: '합성 기업' });
  await waitFor(() =>
    expect(screen.getByTestId('address').textContent).toContain(
      `asOf=${encodeURIComponent(saturday)}`,
    ),
  );
  expect(screen.getByTestId('address').textContent).toContain(
    'graphVersion=v-weekend',
  );
});

test('a graphVersion-only address the API cannot pin to that version explains it cannot open and moves to the latest data', async () => {
  // #358 fallback: when the API does not answer with the requested version, its metadata.asOf is not that
  // version's first public time. The page must not invent one (422) nor wait forever; it offers the latest data.
  server.on('GET', '/api/v1/companies/:id', (r) =>
    json({
      ...company,
      id: r.params.id,
      metadata: {
        ...metadata,
        graphVersion: r.query.get('graphVersion') ? 'v-other' : 'v1',
      },
    }),
  );
  // 남아 있는 사건 시점(graphAsOf)은 복구 뒤 최신 본문보다 이르므로 지우지 않으면 다시 활성화된다.
  open(`?graphVersion=v-past&graphAsOf=${encodeURIComponent(old)}`);
  const notice = await screen.findByText(/그래프 버전\(v-past\)만 있어/);
  expect(
    screen.queryByText('타임라인의 기준 시점을 확인하고 있어요.'),
  ).toBeNull();
  expect(
    screen.queryByText('관계 그래프의 기준 시점을 확인하고 있어요.'),
  ).toBeNull();
  expect(screen.getByTestId('address').textContent).not.toContain('asOf=');
  expect(server.calls('GET', '/api/v1/events')).toHaveLength(0);
  expect(server.calls('GET', '/api/v1/companies/:id/graph')).toHaveLength(0);
  expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(0);
  expect(screen.queryByText(/최신 제공 시점 확인 중/)).toBeNull();
  expect(screen.queryByText(/차트 불러오는 중/)).toBeNull();
  expect(screen.queryByText(/별 종가/)).toBeNull();
  expect(
    server
      .calls('GET', '/api/v1/companies/:id')
      .every((call) => !call.query.has('asOf')),
  ).toBe(true);

  await userEvent.click(
    within(notice.closest('p')!).getByRole('button', {
      name: '최신 자료로 보기',
    }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('address').textContent).toContain(
      `asOf=${encodeURIComponent(time)}`,
    ),
  );
  expect(screen.getByTestId('address').textContent).toContain(
    'graphVersion=v1',
  );
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/events').length).toBeGreaterThan(0),
  );
  expect(
    server.calls('GET', '/api/v1/companies/:id/prices').length,
  ).toBeGreaterThan(0);
  expect(await screen.findByText(/별 종가/)).toBeTruthy();
  expect(screen.queryByText(/그래프 버전\(v-past\)만 있어/)).toBeNull();
  expect(screen.getByTestId('address').textContent).not.toContain('graphAsOf');
  await waitFor(() =>
    expect(
      server
        .calls('GET', '/api/v1/companies/:id/graph')
        .at(-1)
        ?.query.get('asOf'),
    ).toBe(time),
  );
});

// D-COM-04·06 (#358): a version-only address opens at that version's first public time.
test('a graphVersion-only address fills asOf with the first public time of that version', async () => {
  const firstPublic = '2026-09-01T00:00:00.123Z';
  server.on('GET', '/api/v1/companies/:id', (r) =>
    json({
      ...company,
      id: r.params.id,
      metadata: {
        ...metadata,
        asOf:
          r.query.get('asOf') ??
          (r.query.get('graphVersion') ? firstPublic : time),
        graphVersion: r.query.get('graphVersion') ?? 'v1',
      },
    }),
  );
  open('?graphVersion=v-past');
  await waitFor(() =>
    expect(screen.getByTestId('address').textContent).toContain(
      `asOf=${encodeURIComponent(firstPublic)}`,
    ),
  );
  expect(screen.getByTestId('address').textContent).toContain(
    'graphVersion=v-past',
  );
  expect(
    await screen.findByText(
      /그래프 버전\(v-past\)이 처음 공개된 시점\(.+\)으로 보는 중/,
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/그래프 버전\(v-past\)만 있어/)).toBeNull();
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/events').length).toBeGreaterThan(0),
  );
  expect(
    server
      .calls('GET', '/api/v1/events')
      .every((call) => call.query.get('graphVersion') === 'v-past'),
  ).toBe(true);
  // 관계 그래프도 그 버전과 첫 공개 시각으로 조회한다.
  await waitFor(() =>
    expect(
      server.calls('GET', '/api/v1/companies/:id/graph').length,
    ).toBeGreaterThan(0),
  );
  const graphCall = server.calls('GET', '/api/v1/companies/:id/graph').at(-1)!;
  expect(graphCall.query.get('graphVersion')).toBe('v-past');
  expect(graphCall.query.get('asOf')).toBe(firstPublic);
});

test('a graphVersion-only address explains when its first public time cannot be opened', async () => {
  const firstPublic = '2026-09-01T00:00:00.123Z';
  server.on('GET', '/api/v1/companies/:id', (r) =>
    r.query.has('asOf') && r.query.get('graphVersion') === 'v-past'
      ? apiError(422, 'VALIDATION_FAILED')
      : json({
          ...company,
          id: r.params.id,
          metadata: {
            ...metadata,
            asOf: r.query.get('graphVersion') ? firstPublic : time,
            graphVersion: r.query.get('graphVersion') ?? 'v1',
          },
        }),
  );
  // #401 리뷰: 첫 공개 시각 이후라 무시되던 사건 시점도 최신 자료로 돌아갈 때 함께 지운다.
  open(`?graphVersion=v-past&graphAsOf=${encodeURIComponent(old)}`);
  const notice = await screen.findByText(
    /그래프 버전\(v-past\)이 처음 공개된 시점으로 열지 못했어요/,
  );
  await userEvent.click(
    within(notice.closest('p')!).getByRole('button', {
      name: '최신 자료로 보기',
    }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('address').textContent).toContain(
      `asOf=${encodeURIComponent(time)}`,
    ),
  );
  expect(screen.getByTestId('address').textContent).toContain(
    'graphVersion=v1',
  );
  expect(screen.getByTestId('address').textContent).not.toContain('graphAsOf');
  await waitFor(() =>
    expect(
      server
        .calls('GET', '/api/v1/companies/:id/graph')
        .at(-1)
        ?.query.get('asOf'),
    ).toBe(time),
  );
});

test.each(['success', 'failure'] as const)(
  'D-COM-01 discards a late price %s after entering a graphVersion-only address',
  async (outcome) => {
    const pending = deferred<Response>();
    const priceResponse = () =>
      json({
        status: 'available',
        companyId: id,
        period: '1m',
        interval: '1d',
        source,
        currency: 'KRW',
        points: [
          {
            time: old,
            open: 100,
            high: 115,
            low: 90,
            close: 110,
            volume: null,
          },
          { time, open: 110, high: 130, low: 100, close: 120, volume: null },
        ],
      });
    let first = true;
    server.on('GET', '/api/v1/companies/:id/prices', () => {
      if (first) {
        first = false;
        return pending.promise;
      }
      return priceResponse();
    });
    server.on('GET', '/api/v1/companies/:id', (r) =>
      json({
        ...company,
        metadata: {
          ...metadata,
          graphVersion:
            r.query.get('graphVersion') === 'v-past' && !r.query.has('asOf')
              ? 'v-other'
              : (r.query.get('graphVersion') ?? 'v1'),
        },
      }),
    );
    render(
      <MemoryRouter
        initialEntries={[`/companies/${encodeURIComponent(id)}${pinned}`]}
      >
        <Address />
        <VersionOnlyNavigation />
        <Routes>
          <Route path="/companies/:id" element={<CompanyDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(
        1,
      ),
    );
    expect(screen.getByText(/차트 불러오는 중/)).toBeTruthy();
    await userEvent.click(
      screen.getByRole('button', { name: '버전 단독 주소로 이동' }),
    );
    const notice = await screen.findByText(/그래프 버전\(v-past\)만 있어/);
    const assertUnsupported = () => {
      expect(server.calls('GET', '/api/v1/companies/:id/prices')).toHaveLength(
        1,
      );
      expect(screen.getByTestId('address').textContent).toContain(
        'graphVersion=v-past',
      );
      expect(screen.getByTestId('address').textContent).not.toContain('asOf=');
      expect(screen.queryByText(/별 종가/)).toBeNull();
      expect(
        screen.queryByText(
          /차트 불러오는 중|차트 조회 실패|최신 제공 시점 확인 중/,
        ),
      ).toBeNull();
      expect(screen.getByRole('region', { name: '최신 시세' })).toBeTruthy();
    };
    assertUnsupported();
    await act(async () => {
      pending.resolve(
        outcome === 'success'
          ? priceResponse()
          : apiError(503, 'SOURCE_UNAVAILABLE'),
      );
    });
    assertUnsupported();

    await userEvent.click(
      within(notice.closest('p')!).getByRole('button', {
        name: '최신 자료로 보기',
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('address').textContent).toContain(
        `asOf=${encodeURIComponent(time)}`,
      ),
    );
    expect(screen.getByTestId('address').textContent).toContain(
      'graphVersion=v1',
    );
    expect(await screen.findByText(/별 종가/)).toBeTruthy();
    expect(
      server.calls('GET', '/api/v1/companies/:id/prices').length,
    ).toBeGreaterThan(1);
    expect(screen.queryByText(/그래프 버전\(v-past\)만 있어/)).toBeNull();
  },
);

test('D-COM-06: [이 당시 관계그래프 보기] moves only the graph to the event time and [현재] returns', async () => {
  open(pinned);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', {
      name: '합성 사건 A · 이 당시 관계그래프 보기',
    }),
  );
  const address = () => screen.getByTestId('address').textContent ?? '';
  expect(address()).toContain(`graphAsOf=${encodeURIComponent(old)}`);
  expect(address()).toContain(`asOf=${encodeURIComponent(time)}`);
  expect(address()).toContain('event=issue-a');
  await waitFor(() => {
    const last = server.calls('GET', '/api/v1/companies/:id/graph').at(-1)!;
    expect(last.query.get('asOf')).toBe(old);
    // 그 시점의 공개 버전은 서버가 고른다.
    expect(last.query.has('graphVersion')).toBe(false);
  });
  expect(
    server
      .calls('GET', '/api/v1/events')
      .every((call) => call.query.get('asOf') === time),
  ).toBe(true);
  expect(screen.getByText(/사건 시점 .* 기준 관계예요/)).toBeTruthy();

  await user.click(
    await screen.findByRole('button', {
      name: '현재 시점 관계 그래프로 돌아가기',
    }),
  );
  expect(address()).not.toContain('graphAsOf');
  await waitFor(() => {
    const last = server.calls('GET', '/api/v1/companies/:id/graph').at(-1)!;
    expect(last.query.get('asOf')).toBe(time);
    expect(last.query.get('graphVersion')).toBe('v1');
  });
  expect(
    screen.queryByRole('button', { name: '현재 시점 관계 그래프로 돌아가기' }),
  ).toBeNull();
});

test('D-COM-06: day events use the KST day end; month, unknown and later events offer no graph time', async () => {
  server.on('GET', '/api/v1/events', () =>
    json({
      items: [
        { ...events[0], timePrecision: 'day', eventTime: '2026-10-04' },
        {
          ...events[1],
          id: 'issue-month',
          title: '월 사건',
          timePrecision: 'month',
          eventTime: '2026-09',
        },
        {
          ...events[1],
          id: 'issue-later',
          title: '나중 사건',
          eventTime: '2026-10-07T03:00:00Z',
        },
      ],
      unknownTimeItems: [],
      nextCursor: null,
      metadata: { ...metadata, total: 3, excludedUnknownTime: 0 },
    }),
  );
  open(pinned);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', {
      name: '합성 사건 A · 이 당시 관계그래프 보기',
    }),
  );
  expect(screen.getByTestId('address').textContent).toContain(
    `graphAsOf=${encodeURIComponent('2026-10-04T23:59:59+09:00')}`,
  );
  expect(
    screen.queryByRole('button', { name: '월 사건 · 이 당시 관계그래프 보기' }),
  ).toBeNull();
  expect(
    screen.queryByRole('button', {
      name: '나중 사건 · 이 당시 관계그래프 보기',
    }),
  ).toBeNull();
});

test.each(['2026-10-05T12:00:00+09:00', '2026-10-05T03:00:00.000Z'])(
  'D-COM-06: a graph time written differently from the event time still drives the impact path (%s)',
  async (graphTime) => {
    open(`${pinned}&graphAsOf=${encodeURIComponent(graphTime)}&event=issue-a`);
    await waitFor(() => {
      const impact = server
        .calls('GET', '/api/v1/companies/:id/issues/:issueId/impact')
        .filter((call) => call.params.issueId === 'issue-a');
      expect(impact.length).toBeGreaterThan(0);
      expect(impact.at(-1)!.query.get('asOf')).toBe(graphTime);
      expect(impact.at(-1)!.query.has('graphVersion')).toBe(false);
    });
    expect(
      (
        await screen.findByRole('button', {
          name: '합성 사건 A · 이 당시 관계그래프 보기',
        })
      ).getAttribute('aria-pressed'),
    ).toBe('true');
  },
);

test('D-COM-06: an event at the reference time written with an offset offers no graph time', async () => {
  server.on('GET', '/api/v1/events', () =>
    json({
      items: [
        events[0],
        {
          ...events[1],
          id: 'issue-same',
          title: '같은 시각 사건',
          eventTime: '2026-10-06T12:00:00+09:00',
        },
      ],
      unknownTimeItems: [],
      nextCursor: null,
      metadata: { ...metadata, total: 2, excludedUnknownTime: 0 },
    }),
  );
  open(pinned);
  await screen.findByRole('button', {
    name: '합성 사건 A · 이 당시 관계그래프 보기',
  });
  expect(
    screen.queryByRole('button', {
      name: '같은 시각 사건 · 이 당시 관계그래프 보기',
    }),
  ).toBeNull();
});

test('D-COM-06: [최신 시점] also clears the event-time graph', async () => {
  open(`${pinned}&graphAsOf=${encodeURIComponent(old)}`);
  const user = userEvent.setup();
  await screen.findByRole('button', {
    name: '현재 시점 관계 그래프로 돌아가기',
  });
  await user.click(screen.getByRole('button', { name: '최신 시점' }));
  expect(screen.getByTestId('address').textContent).not.toContain('graphAsOf');
});

test('D-COM-06: an event time without a public version still offers the way back', async () => {
  server.on('GET', '/api/v1/companies/:id/graph', (r) =>
    r.query.get('asOf') === old
      ? apiError(409, 'VERSION_UNAVAILABLE')
      : json({ ...graph, metadata: { ...graph.metadata, asOf: time } }),
  );
  open(`${pinned}&graphAsOf=${encodeURIComponent(old)}`);
  const user = userEvent.setup();
  await screen.findByText(/관계 그래프 조회 실패/);
  await user.click(
    screen.getByRole('button', { name: '현재 시점 관계 그래프로 돌아가기' }),
  );
  expect(
    await screen.findByRole('img', { name: '기준 시점 기업 관계 그래프' }),
  ).toBeTruthy();
});

test('D-COM-06: the event-time graph stays while the graph is used and returns to the current time on a click elsewhere', async () => {
  // 사건 B는 A보다 늦다. A 시점 그래프에서 B를 고르면 B를 A 시각으로 조회하면 안 된다.
  server.on('GET', '/api/v1/events', (r) =>
    json({
      items: [events[0], { ...events[1], eventTime: '2026-10-05T12:00:00Z' }],
      unknownTimeItems: [],
      nextCursor: null,
      metadata: {
        ...metadata,
        asOf: r.query.get('asOf') ?? time,
        total: 2,
        excludedUnknownTime: 0,
      },
    }),
  );
  open(pinned);
  const user = userEvent.setup();
  const address = () => screen.getByTestId('address').textContent ?? '';
  await user.click(
    await screen.findByRole('button', {
      name: '합성 사건 A · 이 당시 관계그래프 보기',
    }),
  );
  expect(address()).toContain(`graphAsOf=${encodeURIComponent(old)}`);

  // 그래프 안의 조작(깊이 바꾸기)은 사건 시점을 유지한다.
  const panel = screen.getByRole('complementary', {
    name: '시점 기반 관계 그래프',
  });
  await user.click(within(panel).getByRole('button', { name: '2단계' }));
  await waitFor(() => expect(address()).toContain('depth=2'));
  expect(address()).toContain(`graphAsOf=${encodeURIComponent(old)}`);

  // 그래프 밖에서 다른 사건을 고르면 그 사건은 고르고 그래프는 현재 기준 시점으로 돌아간다.
  await user.click(screen.getByRole('button', { name: '합성 사건 B' }));
  await waitFor(() => expect(address()).not.toContain('graphAsOf'));
  expect(address()).toContain('event=issue-b');
  await waitFor(() => {
    const impact = server
      .calls('GET', '/api/v1/companies/:id/issues/:issueId/impact')
      .filter((call) => call.params.issueId === 'issue-b');
    expect(impact.length).toBeGreaterThan(0);
    expect(impact.every((call) => call.query.get('asOf') === time)).toBe(true);
  });
  await waitFor(() => {
    const last = server.calls('GET', '/api/v1/companies/:id/graph').at(-1)!;
    expect(last.query.get('asOf')).toBe(time);
    expect(last.query.get('graphVersion')).toBe('v1');
  });
});

test('D-COM-06: a graph time that is not earlier than the reference time is ignored', async () => {
  open(`${pinned}&graphAsOf=${encodeURIComponent('2026-10-07T00:00:00Z')}`);
  await screen.findByRole('img', { name: '기준 시점 기업 관계 그래프' });
  expect(
    server
      .calls('GET', '/api/v1/companies/:id/graph')
      .every((call) => call.query.get('asOf') === time),
  ).toBe(true);
  expect(
    screen.queryByRole('button', { name: '현재 시점 관계 그래프로 돌아가기' }),
  ).toBeNull();
});

test('D-COM-06: recovering from an invalid reference time also clears the graph time', async () => {
  open(`?asOf=bad&graphAsOf=${encodeURIComponent(old)}`);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '최신 제공 시점으로 조회' }),
  );
  expect(screen.getByTestId('address').textContent).not.toContain('graphAsOf');
});

// D-COM-01 / F6-F7: synthetic API responses verify display only; request selectors remain unchanged.
function formattingQuote(
  currency = 'KRW',
  change: number | null = 2,
  observedAt: string | null = time,
  price: number | null = 120,
) {
  return {
    status: 'available',
    companyId: id,
    source,
    quote: {
      price,
      currency,
      asOf: observedAt,
      change,
      changeRate: change === null ? null : 0.02,
      volume: null,
      dayLow: null,
      dayHigh: null,
      fiftyTwoWeekLow: null,
      fiftyTwoWeekHigh: null,
    },
  };
}

test.each([
  ['KRW', '120원', '▲ +2원 (+2.00%)'],
  ['USD', '$120.00', '▲ +$2.00 (+2.00%)'],
])(
  'D-COM-01 F7 formats %s price and day change with currency',
  async (currency, price, change) => {
    server.on('GET', '/api/v1/companies/:id/quote', () =>
      json(formattingQuote(currency)),
    );
    open(pinned);
    const region = within(
      await screen.findByRole('region', { name: '최신 시세' }),
    );
    expect(await region.findByText(price, { exact: true })).toBeTruthy();
    expect(region.getByText(change, { exact: true })).toBeTruthy();
  },
);

test('D-COM-01 F7 preserves missing quote amounts instead of fabricating zero', async () => {
  server.on('GET', '/api/v1/companies/:id/quote', () =>
    json(formattingQuote('KRW', null, null, null)),
  );
  open(pinned);
  const region = within(
    await screen.findByRole('region', { name: '최신 시세' }),
  );
  expect(
    await region.findByText('미제공', { exact: true, selector: 'strong' }),
  ).toBeTruthy();
  expect(region.getByText('미제공 (미제공)', { exact: true })).toBeTruthy();
  expect(region.queryByText('0원', { exact: true })).toBeNull();
  expect(region.getByText(/공급자 관측 시각 미제공/)).toBeTruthy();
});

test('D-COM-01 F7 keeps zero as a real amount', async () => {
  server.on('GET', '/api/v1/companies/:id/quote', () =>
    json(formattingQuote('KRW', 0, time, 0)),
  );
  open(pinned);
  const region = within(
    await screen.findByRole('region', { name: '최신 시세' }),
  );
  expect(await region.findByText('0원', { exact: true })).toBeTruthy();
  expect(region.getByText('0원 (+2.00%)', { exact: true })).toBeTruthy();
});

test('D-COM-01 F6 shows KST while preserving original metadata and observation times', async () => {
  open(pinned);
  const companyRegion = await screen.findByRole('region', {
    name: '기업 개요',
  });
  const basis = await within(companyRegion).findByText('2026-10-06 12:00 KST', {
    exact: true,
  });
  expect(basis.tagName).toBe('TIME');
  expect(basis.getAttribute('datetime')).toBe(time);
  const quoteRegion = screen.getByRole('region', { name: '최신 시세' });
  const observed = await within(quoteRegion).findByText(
    '2026-10-06 12:00 KST',
    { exact: true },
  );
  expect(observed.getAttribute('datetime')).toBe(time);
  expect(within(quoteRegion).getByText(/공급자 관측/).textContent).toContain(
    '공급자 관측 2026-10-06 12:00 KST',
  );
  const last = server.calls('GET', '/api/v1/companies/:id').at(-1)!;
  expect(last.query.get('asOf')).toBe(time);
  expect(last.query.get('graphVersion')).toBe('v1');
});

test('D-COM-01 F6 preserves chart timestamps while B1 keeps unsupported financials hidden', async () => {
  server.on('GET', '/api/v1/companies/:id/financials', () =>
    json({
      status: 'available',
      items: [
        {
          name: '합성 지표',
          period: '합성 기간',
          value: 0,
          unit: '원',
          accountingBasis: null,
          source: 'synthetic',
          asOf: old,
        },
      ],
      metadata,
    }),
  );
  open(pinned);
  await userEvent.click(await screen.findByText('표로 보기', { exact: true }));
  const table = screen.getByRole('table');
  const cell = await within(table).findByText('2026-10-05 12:00 KST', {
    exact: true,
  });
  expect(cell.getAttribute('datetime')).toBe(old);
  expect(server.calls('GET', '/api/v1/companies/:id/financials')).toHaveLength(
    0,
  );
  expect(screen.queryByRole('region', { name: '핵심 재무' })).toBeNull();
});

test('D-COM-01 F6 shows unknown-time event report times in KST and keeps missing ones', async () => {
  server.on('GET', '/api/v1/events', () =>
    json({
      items: [],
      unknownTimeItems: [
        {
          ...events[0],
          id: 'issue-u1',
          title: '합성 시점 미상 A',
          eventTime: null,
          timePrecision: 'unknown',
        },
        {
          ...events[1],
          id: 'issue-u2',
          title: '합성 시점 미상 B',
          eventTime: null,
          timePrecision: 'unknown',
          reportedAt: null,
        },
      ],
      nextCursor: null,
      metadata: { ...metadata, total: 0, excludedUnknownTime: 2 },
    }),
  );
  open(pinned);
  const summary = await screen.findByText('시점 미상 사건 2건');
  await userEvent.click(summary);
  const unknown = within(summary.closest('details')!);
  const reported = unknown.getByText('2026-10-05 12:00 KST', { exact: true });
  expect(reported.tagName).toBe('TIME');
  expect(reported.getAttribute('datetime')).toBe(old);
  expect(reported.parentElement!.textContent).toContain(
    '보도 시각 2026-10-05 12:00 KST (사건 시각 아님)',
  );
  expect(
    unknown.getByRole('button', { name: '합성 시점 미상 B' }).parentElement!
      .textContent,
  ).toContain('보도 시각 미상 (사건 시각 아님)');
});

test('D-COM-01 B1 makes no unsupported financials request or financial section', async () => {
  open(pinned);
  await screen.findByRole('heading', { name: '합성 기업', level: 1 });
  expect(server.calls('GET', '/api/v1/companies/:id/financials')).toHaveLength(
    0,
  );
  expect(screen.queryByRole('region', { name: '핵심 재무' })).toBeNull();
});

test.each([
  [2, 0.02, 'KRW', '▲ +2원 (+2.00%)', 'text-zoop-up'],
  [-2, -0.02, 'KRW', '▼ -2원 (-2.00%)', 'text-zoop-down'],
  [0, 0, 'KRW', '0원 (0.00%)', 'text-zoop-muted'],
  [null, -0.02, 'KRW', '▼ 미제공 (-2.00%)', 'text-zoop-down'],
  [2, null, 'KRW', '▲ +2원 (미제공)', 'text-zoop-up'],
  [null, null, 'KRW', '미제공 (미제공)', 'text-zoop-muted'],
  [0, 0.02, 'KRW', '0원 (+2.00%)', 'text-zoop-muted'],
  [2, -0.02, 'KRW', '▲ +2원 (-2.00%)', 'text-zoop-up'],
  [-2, -0.02, 'USD', '▼ -$2.00 (-2.00%)', 'text-zoop-down'],
] as const)(
  'D-COM-01 N-i shows change %s and rate %s in %s with the change direction and each value sign',
  async (change, rate, currency, label, color) => {
    const response = formattingQuote(currency, change);
    response.quote.changeRate = rate;
    server.on('GET', '/api/v1/companies/:id/quote', () => json(response));
    open(pinned);
    const region = within(
      await screen.findByRole('region', { name: '최신 시세' }),
    );
    const indicator = await region.findByText(label, { exact: true });
    expect(indicator.classList.contains(color)).toBe(true);
    expect(indicator.classList.contains('text-caption')).toBe(false);
    expect(indicator.classList.contains('mt-0.5')).toBe(false);
  },
);

test.each([
  ['datetime', '2026-10-05T03:00:00Z', '2026-10-05 12:00 KST'],
  ['day', '2026-10-05', '2026-10-05'],
  ['month', '2026-10', '2026-10'],
  ['year', '2026', '2026'],
  ['unknown', '2026-10-05', '시점 미상'],
  ['unknown', null, '시점 미상'],
  ['datetime', '2026-10-05T03:00:00', '시점 미상'],
] as const)(
  'D-COM-01 N-k displays %s event time %s without inventing precision',
  async (precision, eventTime, label) => {
    server.on('GET', '/api/v1/events', () =>
      json({
        items: [{ ...events[0], timePrecision: precision, eventTime }],
        unknownTimeItems: [],
        nextCursor: null,
        metadata: { ...metadata, total: 1, excludedUnknownTime: 0 },
      }),
    );
    open(pinned);
    const title = await screen.findByRole('button', { name: '합성 사건 A' });
    const row = within(title.closest('article')!);
    const stamp = await row.findByText(label, {
      exact: true,
      selector: eventTime ? 'time' : 'p',
    });
    if (eventTime) expect(stamp.getAttribute('datetime')).toBe(eventTime);
    else expect(title.closest('article')!.querySelector('time')).toBeNull();
    expect(screen.getByTestId('address').textContent).toContain(pinned);
    expect(screen.getByTestId('address').textContent).not.toContain(
      'graphAsOf',
    );
  },
);

test('D-COM-01 N-x formats an available holding value and keeps an unknown buy currency', async () => {
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: {
      id: 'synthetic-member',
      email: 'synthetic@example.test',
      displayName: '가상',
    },
    setup: { completed: true, tutorialCompleted: false },
    csrfToken: 'synthetic',
    expiresAt: null,
  });
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      holdings: [
        {
          companyId: id,
          quantity: 20,
          avgPrice: 1500,
          avgPriceCurrency: null,
          marketValue: 2400,
          weight: 1,
          quote: { status: 'available', currency: 'KRW' },
        },
      ],
      mockAsOf: old,
      valuation: null,
      metadata,
    }),
  );
  open(pinned);
  await screen.findByText('20주');
  expect(screen.getByText('2,400원', { selector: 'dd' })).toBeTruthy();
  expect(screen.getByText('1,500 통화 미상', { selector: 'dd' })).toBeTruthy();
});

test('D-COM-01 N-x keeps fractional won and formats other currencies like the price', () => {
  expect(money(71234.56, 'KRW')).toBe('71,234.56원');
  expect(money(71000, 'KRW')).toBe('71,000원');
  expect(money(12.5, 'USD')).toBe('$12.50');
  expect(money(null, 'KRW')).toBe('미제공');
});
