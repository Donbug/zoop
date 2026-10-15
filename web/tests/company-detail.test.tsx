import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import CompanyDetailPage from '@/pages/company/CompanyDetailPage';
import MapPage from '@/pages/map/MapPage';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  bucketKey,
  impactEdges,
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
      assertionStatus: 'confirmed',
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
      ],
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
      articles: [],
      relations: [],
      evidenceIds: ['ev-a'],
      metadata: { ...metadata, asOf: r.query.get('asOf') ?? time },
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

test('direct URL defaults to one month and supplied timestamp/version; quote stays latest', async () => {
  open();
  await screen.findByRole('heading', { name: '합성 기업' });
  await screen.findByRole('img', { name: '공급된 종가 차트' });
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
test('same bucket exposes count then individual cards and exact selected event time', async () => {
  open(pinned);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '2026-10-05 · 사건 2건' }),
  );
  await user.click(screen.getByRole('button', { name: '합성 사건 A' }));
  await screen.findByRole('heading', { name: '합성 사건 A' });
  expect(screen.getByTestId('address').textContent).toContain('event=issue-a');
  await waitFor(() =>
    expect(
      server
        .calls('GET', '/api/v1/companies/:id/graph')
        .at(-1)
        ?.query.get('asOf'),
    ).toBe(old),
  );
});
test('chart selection updates historical requests; period retains snapshot and changes resolution', async () => {
  open(pinned);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: `차트 ${old} 선택` }),
  );
  await waitFor(() =>
    expect(
      server.calls('GET', '/api/v1/events').at(-1)?.query.get('asOf'),
    ).toBe(old),
  );
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
    await screen.findByRole('img', { name: '공급된 종가 차트' }),
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
  expect(screen.getByText('계산 불가')).toBeTruthy();
  const region = screen.getByRole('region', { name: '가상 계좌 보유' });
  expect(within(region).getAllByText(/모의/).length).toBeGreaterThan(0);
  await act(async () => useAuthStore.getState().clearSession());
  expect(screen.queryByText('20주')).toBeNull();
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
  await screen.findByText('연결된 가상 계좌가 없어요.');
});
test('map round trip restores period, time, tab, event and bucket exactly; only real path highlighted', async () => {
  const query = `${pinned}&period=1m&tab=events&event=issue-a&bucket=2026-10-05`;
  open(query);
  await screen.findByRole('heading', { name: '합성 사건 A' });
  await userEvent.click(
    screen.getByRole('link', { name: '이 사건의 관계를 지도에서 보기' }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('map-highlight').textContent).toBe('edge-a'),
  );
  expect(
    server
      .calls('GET', '/api/v1/companies/:id/graph')
      .at(-1)
      ?.query.get('graphVersion'),
  ).toBe('v1');
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
  expect(screen.queryByRole('img', { name: '공급된 종가 차트' })).toBeNull();
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
