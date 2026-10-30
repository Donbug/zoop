import { BriefingGraphUnavailableError } from '@/apis/graph/briefing-context';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MapPage from '@/pages/map/MapPage';
import * as impactApi from '@/apis/graph/impact';
import * as companyDataHook from '@/hooks/useCompanyData';
import * as evidenceApi from '@/apis/evidence/evidence';
import { getGraph } from '@/apis/graph/graph';
import { getBriefingGraphBasis } from '@/apis/briefing/briefing';
import { setTutorialCompleted } from '@/apis/graph/tutorial';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { focusNeighborhood } from '@/components/graph/graph-model';
import { createMockGraph } from '@/mocks/graph/response';
import { createMockEvidence } from '@/mocks/evidence/fixture';
import { useAuthStore } from '@/stores/useAuthStore';
import type { GraphResponse } from '@/types/map/graph';
import { createFakeServer, json } from '../support/fakeServer';
import { myMember } from '../support/myMember';
import { connectedPortfolioBody, SAMSUNG_HOLDING } from '../support/fixtures';

vi.mock('@/apis/graph/graph', () => ({ getGraph: vi.fn() }));
vi.mock('@/apis/briefing/briefing', () => ({ getBriefingGraphBasis: vi.fn() }));
vi.mock('@/apis/graph/tutorial', () => ({ setTutorialCompleted: vi.fn() }));
vi.mock('@/components/graph/GraphCanvas', () => ({
  default: ({
    data,
    selectedId,
    focusId,
    focusHops,
    memoryOwner,
    onSelect,
    onTutorialAction,
    tutorialTargetId,
    highlightedEdgeIds,
    isolateSelection,
    centerRequest,
  }: {
    tutorialTargetId?: string;
    onTutorialAction?: (action: 'pan' | 'zoom') => void;
    data: GraphResponse;
    selectedId: string | null;
    focusId: string | null;
    focusHops: 1 | 2;
    memoryOwner: string;
    onSelect: (id: string) => void;
    highlightedEdgeIds: string[];
    isolateSelection?: boolean;
    centerRequest?: { id: string; seq: number } | null;
  }) => (
    <div
      data-testid="graph-canvas"
      data-tutorial-target={tutorialTargetId}
      data-focus={focusId ?? ''}
      data-hops={focusHops}
      data-view-owner={memoryOwner}
      data-highlighted={highlightedEdgeIds.join(',')}
      data-isolate={isolateSelection ? 'yes' : 'no'}
      data-center={centerRequest?.id ?? ''}
    >
      {onTutorialAction && (
        <>
          <button
            data-tutorial-action="move"
            onClick={() => onTutorialAction('pan')}
          >
            지도 이동 실습
          </button>
          <button
            data-tutorial-action="zoom"
            onClick={() => onTutorialAction('zoom')}
          >
            지도 확대 실습
          </button>
        </>
      )}
      {data.nodes.map((node) => (
        <button
          key={node.id}
          data-tutorial-action={
            node.id === tutorialTargetId ? 'node' : undefined
          }
          onClick={() => onSelect(node.id)}
          aria-pressed={selectedId === node.id}
        >
          {node.label} 선택
        </button>
      ))}
    </div>
  ),
}));

function anonymous() {
  useAuthStore.setState({
    status: 'ready',
    session: {
      authenticated: false,
      kind: 'anonymous',
      user: null,
      setup: null,
      csrfToken: null,
      expiresAt: null,
    },
    member: null,
    onboardingCompleted: null,
  });
}

function member() {
  useAuthStore.setState({
    status: 'ready',
    session: {
      authenticated: true,
      kind: 'member',
      user: { id: 'member-1', email: 'member@zoop.test', displayName: '도현' },
      setup: { completed: true, tutorialCompleted: false },
      csrfToken: 'csrf',
      expiresAt: null,
    },
    member: { id: 'member-1', email: 'member@zoop.test', displayName: '도현' },
    onboardingCompleted: true,
  });
}

function setup(url = '/?mode=all') {
  const router = createMemoryRouter([{ path: '/', element: <MapPage /> }], {
    initialEntries: [url],
  });
  render(<RouterProvider router={router} />);
  return router;
}

it('D-GRP-01 opens the sidebar on wide screens and remembers an explicit close', async () => {
  anonymous();
  localStorage.removeItem('zoop:sidebar-open');
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
  vi.mocked(getGraph).mockResolvedValue(
    createMockGraph({ mode: 'all', personalFilter: 'all' }),
  );
  const router = createMemoryRouter([{ path: '/', element: <MapPage /> }], {
    initialEntries: ['/'],
  });
  const rendered = render(<RouterProvider router={router} />);
  expect(
    await screen.findByRole('complementary', { name: '내 종목' }),
  ).toBeTruthy();
  await userEvent.click(
    screen.getByRole('button', { name: '내 종목 사이드바 닫기' }),
  );
  expect(localStorage.getItem('zoop:sidebar-open')).toBe('0');
  rendered.unmount();
  const second = createMemoryRouter([{ path: '/', element: <MapPage /> }], {
    initialEntries: ['/'],
  });
  render(<RouterProvider router={second} />);
  await screen.findByTestId('graph-canvas');
  expect(screen.queryByRole('complementary', { name: '내 종목' })).toBeNull();
  localStorage.removeItem('zoop:sidebar-open');
  vi.unstubAllGlobals();
});

it('D-GRP-01b opens the excluded holding in the full graph only after a successful read', async () => {
  member();
  const session = useAuthStore.getState().session!;
  useAuthStore.setState({
    session: {
      ...session,
      setup: { completed: true, tutorialCompleted: true },
    },
  });
  localStorage.setItem('zoop:sidebar-open', '1');
  const server = createFakeServer();
  myMember(server, { connected: true });
  server.on('GET', '/api/v1/portfolio', () =>
    json(
      connectedPortfolioBody([{ ...SAMSUNG_HOLDING, companyId: 'KRX:005930' }]),
    ),
  );
  vi.mocked(getGraph).mockImplementation(async (request) =>
    createMockGraph(request),
  );
  const router = setup('/?mode=personal&scope=watchlist');
  await userEvent.click(
    await screen.findByRole('button', { name: '삼성전자, 지도에서 보기' }),
  );
  expect(screen.getByText(/이 종목은 지금 지도에 없어요/)).toBeTruthy();
  await userEvent.click(screen.getByRole('button', { name: '전체로 보기' }));
  await waitFor(() =>
    expect(
      new URLSearchParams(router.state.location.search).get('select'),
    ).toBe('node:KRX:005930'),
  );
  expect(new URLSearchParams(router.state.location.search).get('mode')).toBe(
    'all',
  );
  localStorage.removeItem('zoop:sidebar-open');
});

it('D-GRP-01b keeps the personal graph when full graph loading fails', async () => {
  member();
  const session = useAuthStore.getState().session!;
  useAuthStore.setState({
    session: {
      ...session,
      setup: { completed: true, tutorialCompleted: true },
    },
  });
  localStorage.setItem('zoop:sidebar-open', '1');
  const server = createFakeServer();
  myMember(server, { connected: true });
  server.on('GET', '/api/v1/portfolio', () =>
    json(
      connectedPortfolioBody([{ ...SAMSUNG_HOLDING, companyId: 'KRX:005930' }]),
    ),
  );
  vi.mocked(getGraph).mockImplementation(async (request) => {
    if (request.mode === 'all') throw new Error('source offline');
    return createMockGraph(request);
  });
  const router = setup('/?mode=personal&scope=watchlist');
  await userEvent.click(
    await screen.findByRole('button', { name: '삼성전자, 지도에서 보기' }),
  );
  await userEvent.click(screen.getByRole('button', { name: '전체로 보기' }));
  expect(await screen.findByText(/지도 전환 실패/)).toBeTruthy();
  expect(new URLSearchParams(router.state.location.search).get('mode')).toBe(
    'personal',
  );
  expect(new URLSearchParams(router.state.location.search).has('select')).toBe(
    false,
  );
  localStorage.removeItem('zoop:sidebar-open');
});

it('D-GRP-01b does not reuse an excluded company after the member changes', async () => {
  member();
  const session = useAuthStore.getState().session!;
  useAuthStore.setState({
    session: {
      ...session,
      setup: { completed: true, tutorialCompleted: true },
    },
  });
  localStorage.setItem('zoop:sidebar-open', '1');
  const server = createFakeServer();
  myMember(server, { connected: true });
  server.on('GET', '/api/v1/portfolio', () =>
    json(
      connectedPortfolioBody([{ ...SAMSUNG_HOLDING, companyId: 'KRX:005930' }]),
    ),
  );
  vi.mocked(getGraph).mockImplementation(async (request) =>
    createMockGraph(request),
  );
  setup('/?mode=personal&scope=watchlist');
  await userEvent.click(
    await screen.findByRole('button', { name: '삼성전자, 지도에서 보기' }),
  );
  expect(screen.getByRole('button', { name: '전체로 보기' })).toBeTruthy();
  act(() => {
    const state = useAuthStore.getState();
    const nextMember = {
      id: 'different-member',
      email: 'different@zoop.test',
      displayName: '다른 회원',
    };
    useAuthStore.setState({
      member: nextMember,
      session: { ...state.session!, user: nextMember },
      sessionRevision: state.sessionRevision + 1,
    });
  });
  expect(screen.queryByRole('button', { name: '전체로 보기' })).toBeNull();
  localStorage.removeItem('zoop:sidebar-open');
});

it('D-GRP-01 sidebar selection exits path and focus modes', async () => {
  member();
  const session = useAuthStore.getState().session!;
  useAuthStore.setState({
    session: {
      ...session,
      setup: { completed: true, tutorialCompleted: true },
    },
  });
  localStorage.setItem('zoop:sidebar-open', '1');
  const server = createFakeServer();
  myMember(server, { connected: true });
  server.on('GET', '/api/v1/portfolio', () =>
    json(
      connectedPortfolioBody([{ ...SAMSUNG_HOLDING, companyId: 'KRX:005930' }]),
    ),
  );
  vi.mocked(getGraph).mockImplementation(async (request) =>
    createMockGraph(request),
  );
  const router = setup(
    '/?mode=all&path=KRX%3A005930%2CNASDAQ%3ANVDA&focus=mock-issue-1&hops=2',
  );
  await userEvent.click(
    await screen.findByRole('button', { name: '삼성전자, 지도에서 보기' }),
  );
  await waitFor(() =>
    expect(
      new URLSearchParams(router.state.location.search).get('select'),
    ).toBe('node:KRX:005930'),
  );
  expect(new URLSearchParams(router.state.location.search).has('path')).toBe(
    false,
  );
  expect(new URLSearchParams(router.state.location.search).has('focus')).toBe(
    false,
  );
  localStorage.removeItem('zoop:sidebar-open');
});

function sidebarMember() {
  member();
  const session = useAuthStore.getState().session!;
  useAuthStore.setState({
    session: {
      ...session,
      setup: { completed: true, tutorialCompleted: true },
    },
  });
  localStorage.setItem('zoop:sidebar-open', '1');
  const server = createFakeServer();
  myMember(server, { connected: true });
  server.on('GET', '/api/v1/portfolio', () =>
    json(
      connectedPortfolioBody([{ ...SAMSUNG_HOLDING, companyId: 'KRX:005930' }]),
    ),
  );
}

// #388 리뷰 1: 개인화 전환 조회가 끝나기 전에 관심을 저장하면, 저장 전 목록으로 받은 응답을 쓰지 않는다.
it('FS027 restarts a pending personal switch after a watch is saved', async () => {
  sidebarMember();
  let releaseFirst!: () => void;
  let personalCalls = 0;
  vi.mocked(getGraph).mockImplementation(async (request) => {
    if (request.mode === 'personal' && ++personalCalls === 1)
      await new Promise<void>((resolve) => {
        releaseFirst = resolve;
      });
    return createMockGraph(request);
  });
  const router = setup('/?mode=all');
  await screen.findByRole('button', { name: '삼성전자, 지도에서 보기' });
  await userEvent.click(
    within(screen.getByLabelText('그래프 모드')).getByRole('button', {
      name: '내 종목',
    }),
  );
  await waitFor(() => expect(personalCalls).toBe(1));
  await userEvent.click(
    screen.getByRole('button', { name: '삼성전자 관심 종목' }),
  );
  await waitFor(() => expect(personalCalls).toBe(2));
  await act(async () => releaseFirst());
  await waitFor(() =>
    expect(new URLSearchParams(router.state.location.search).get('mode')).toBe(
      'personal',
    ),
  );
  expect(personalCalls).toBe(2);
  localStorage.removeItem('zoop:sidebar-open');
});

// #388 리뷰 3: 사이드바에서 연 상세를 닫으면 고른 행으로 포커스가 돌아온다.
it('D-GRP-01 returns focus to the sidebar row after closing its detail', async () => {
  sidebarMember();
  vi.mocked(getGraph).mockImplementation(async (request) =>
    createMockGraph(request),
  );
  setup('/?mode=all');
  const row = await screen.findByRole('button', {
    name: '삼성전자, 지도에서 보기',
  });
  await userEvent.click(row);
  await userEvent.click(
    await screen.findByRole('button', { name: '기업 상세 닫기' }),
  );
  await waitFor(() => expect(document.activeElement).toBe(row));
  localStorage.removeItem('zoop:sidebar-open');
});

it('D-GRP-07 restores a pair from URL, lets the user repick and closes without changing the graph mode', async () => {
  anonymous();
  vi.mocked(getGraph).mockResolvedValue(
    createMockGraph({ mode: 'all', personalFilter: 'all' }),
  );
  const router = setup('/?mode=all&path=KRX%3A005930%2CNASDAQ%3ANVDA');
  const panel = await screen.findByRole('complementary', {
    name: '두 기업 사이 경로',
  });
  await within(panel).findByRole('heading', { name: '2단계 연결' });
  expect(within(panel).getAllByText('삼성전자').length).toBeGreaterThan(0);
  await userEvent.click(
    within(panel).getByRole('button', { name: '다른 기업 고르기' }),
  );
  await userEvent.click(
    within(panel).getByRole('button', { name: /^NVIDIA$/ }),
  );
  expect(new URLSearchParams(router.state.location.search).get('path')).toBe(
    'KRX:005930,NASDAQ:NVDA',
  );
  await act(async () => {
    await router.navigate(-1);
  });
  await within(panel).findByRole('heading', { name: '두 번째 기업 선택' });
  await act(async () => {
    await router.navigate(1);
  });
  await within(panel).findByRole('heading', { name: '2단계 연결' });
  await userEvent.click(
    within(panel).getByRole('button', { name: '경로 닫기' }),
  );
  expect(new URLSearchParams(router.state.location.search).has('path')).toBe(
    false,
  );
  expect(new URLSearchParams(router.state.location.search).get('mode')).toBe(
    'all',
  );
});

it('D-GRP-07 selects a path company and leaves path and focus mode', async () => {
  anonymous();
  vi.mocked(getGraph).mockResolvedValue(
    createMockGraph({ mode: 'all', personalFilter: 'all' }),
  );
  const router = setup(
    '/?mode=all&path=KRX%3A005930%2CNASDAQ%3ANVDA&focus=mock-issue-1&hops=2',
  );
  const panel = await screen.findByRole('complementary', {
    name: '두 기업 사이 경로',
  });
  await userEvent.click(
    await within(panel).findByRole('button', { name: '삼성전자' }),
  );
  const params = new URLSearchParams(router.state.location.search);
  expect(params.get('select')).toBe('node:KRX:005930');
  expect(params.has('path')).toBe(false);
  expect(params.has('focus')).toBe(false);
});

it('D-GRP-05 highlights only edges supported by the selected evidence and clears on close', async () => {
  anonymous();
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  vi.mocked(getGraph).mockResolvedValue(graph);
  vi.spyOn(evidenceApi, 'getEvidence').mockImplementation(async (id) =>
    createMockEvidence(id),
  );
  setup();
  await screen.findByTestId('graph-canvas');
  act(() =>
    useGraphUiStore.getState().openEvidence({
      kind: 'issue',
      id: 'mock-issue-1',
      label: '사건',
      evidenceIds: ['mock-evidence-1'],
      mapContext: {
        graphVersion: graph.metadata.graphVersion ?? undefined,
        asOf: graph.metadata.asOf,
        url: '/',
      },
    }),
  );
  await userEvent.click(
    await screen.findByRole('button', { name: '◇ 지도에서 보기' }),
  );
  const expected = graph.edges
    .filter((edge) => edge.evidenceIds.includes('mock-evidence-1'))
    .map((edge) => edge.id);
  expect(expected.length).toBeGreaterThan(0);
  expect(
    screen.getByTestId('graph-canvas').getAttribute('data-highlighted'),
  ).toBe(expected.join(','));
  await userEvent.click(screen.getByRole('button', { name: '근거 창 닫기' }));
  expect(
    screen.getByTestId('graph-canvas').getAttribute('data-highlighted'),
  ).toBe('');
  vi.restoreAllMocks();
});

it('D-GRP-05 isolates the related event when no edge has that evidence', async () => {
  anonymous();
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  graph.edges = graph.edges.map((edge) => ({ ...edge, evidenceIds: [] }));
  vi.mocked(getGraph).mockResolvedValue(graph);
  vi.spyOn(evidenceApi, 'getEvidence').mockImplementation(async (id) =>
    createMockEvidence(id),
  );
  setup();
  await screen.findByTestId('graph-canvas');
  act(() =>
    useGraphUiStore.getState().openEvidence({
      kind: 'issue',
      id: 'mock-issue-1',
      label: '사건',
      evidenceIds: ['mock-evidence-1'],
      mapContext: {
        graphVersion: graph.metadata.graphVersion ?? undefined,
        asOf: graph.metadata.asOf,
        url: '/',
      },
    }),
  );
  await userEvent.click(
    await screen.findByRole('button', { name: '◇ 지도에서 보기' }),
  );
  expect(
    screen.getByTestId('graph-canvas').getAttribute('data-highlighted'),
  ).toBe('');
  expect(screen.getByTestId('graph-canvas').getAttribute('data-isolate')).toBe(
    'yes',
  );
  vi.restoreAllMocks();
});

it('D-GRP-01 keeps event focus and map information controls without the extra help button', async () => {
  anonymous();
  vi.mocked(getGraph).mockResolvedValue(
    createMockGraph({ mode: 'all', personalFilter: 'all' }),
  );
  const router = setup('/?mode=all&focus=mock-issue-1&hops=1');
  expect(await screen.findByRole('group', { name: /중심 보기/ })).toBeTruthy();
  await userEvent.click(
    screen.getByRole('radio', { name: '2단계: 이웃의 이웃까지' }),
  );
  expect(new URLSearchParams(router.state.location.search).get('hops')).toBe(
    '2',
  );
  // D-GRP-01 / F5: mobile targets grow without changing desktop recipes.
  // The existing graph typography applies an important 28px minimum.
  expect(
    document
      .querySelector('.relationship-map')!
      .classList.contains(
        'max-md:[&_.relationship-graph-filters_button]:min-h-10!',
      ),
  ).toBe(true);
  for (const name of ['지도 데이터 안내', '튜토리얼 다시 보기']) {
    const button = screen.getByRole('button', { name });
    expect(button.classList.contains('max-md:min-h-10')).toBe(true);
    expect(button.classList.contains('max-md:min-w-10')).toBe(true);
  }
  expect(screen.queryByRole('button', { name: '조작 도움말' })).toBeNull();
});

it('D-BRF-04 회차 지도를 최신 main 지도에 연결하고 현재 지도로 복귀한다', async () => {
  anonymous();
  vi.mocked(getGraph).mockImplementation(async (request) =>
    createMockGraph(request),
  );
  const roundId = 'brf-2026-09-17-evening';
  vi.mocked(getBriefingGraphBasis).mockResolvedValue({
    roundId,
    date: '2026-09-17',
    edition: 'evening',
    status: 'available',
    message: null,
    reason: null,
    publishedAt: '2026-09-17T09:11:00Z',
    dataAsOf: '2026-09-17T09:10:00Z',
    graphVersion: 'fixture-v1',
    keyIssueIds: [],
    companyIds: [],
    correctionCount: 0,
  });
  const router = setup(`/?mode=all&round=${roundId}`);
  await screen.findByTestId('graph-canvas');
  expect(
    screen.getByTestId('graph-canvas').getAttribute('data-view-owner'),
  ).toContain(`:round:${roundId}`);
  expect(
    vi
      .mocked(getGraph)
      .mock.calls.some(([request]) => request.round === roundId),
  ).toBe(true);
  expect(
    await screen.findByRole('region', { name: '브리핑 회차 기준 지도' }),
  ).toBeTruthy();
  expect(
    screen
      .getByTestId('graph-canvas')
      .closest('section')
      ?.getAttribute('data-screen-id'),
  ).toBe('D-BRF-04');
  await userEvent.click(
    screen.getByRole('button', { name: '현재 그래프로 보기' }),
  );
  await waitFor(() =>
    expect(vi.mocked(getGraph).mock.calls.at(-1)?.[0].round).toBeUndefined(),
  );
  expect(router.state.location.search).not.toContain('round=');
});

it('과거 회차 저장본 부재는 재시도 오류와 구분하고 현재 그래프로 이동할 수 있다', async () => {
  anonymous();
  const basis = {
    roundId: 'sim-2026-10-08-morning-original',
    date: '2026-10-08',
    edition: 'morning' as const,
    status: 'unavailable' as const,
    message: '이 회차에는 발행 당시 저장된 그래프가 없습니다.',
    reason: null,
    publishedAt: '2026-10-16T00:30:00Z',
    dataAsOf: '2026-10-08T00:20:00Z',
    graphVersion: null,
    keyIssueIds: [],
    companyIds: [],
    correctionCount: 0,
    unavailableReason: 'snapshot_not_recorded' as const,
  };
  vi.mocked(getBriefingGraphBasis).mockResolvedValue(basis);
  vi.mocked(getGraph).mockImplementation(async (request) => {
    if (request.round) throw new BriefingGraphUnavailableError(basis);
    return createMockGraph(request);
  });
  const router = setup(`/?round=${basis.roundId}`);
  await screen.findAllByText(basis.message);
  expect(screen.queryByText(/조회 실패:/)).toBeNull();
  expect(screen.getByText('이 회차의 그래프 저장본이 없습니다.')).toBeTruthy();
  expect(screen.queryByText('관계 지도를 불러오지 못했습니다.')).toBeNull();
  expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull();
  expect(
    screen.getByRole('link', { name: '브리핑으로' }).getAttribute('href'),
  ).toContain('date=2026-10-08&edition=morning');
  await userEvent.click(
    screen.getByRole('button', { name: '현재 그래프로 보기' }),
  );
  await screen.findByTestId('graph-canvas');
  expect(router.state.location.search).not.toContain('round=');
});

describe('D-GRP-T~T5 · 관계 그래프 튜토리얼', () => {
  it.each(['linked', 'cancelled', 'failed'])(
    '#381 튜토리얼로 주소를 정리해도 소셜 계정 연결 결과(%s)는 남기고 그 밖의 값은 지운다',
    async (result) => {
      const router = setup(
        `/?social=${result}&code=abc&state=xyz&select=node:KRX:005930&tour=1`,
      );
      await screen.findByRole('heading', { name: '지도 움직이기' });
      const params = new URLSearchParams(router.state.location.search);
      expect(params.get('social')).toBe(result);
      expect(params.get('mode')).toBe('all');
      expect(params.get('tour')).toBe('1');
      expect([...params.keys()].sort()).toEqual(['mode', 'social', 'tour']);
    },
  );
  it('#381 알 수 없는 social 값은 튜토리얼 주소에 남기지 않는다', async () => {
    const router = setup('/?social=other&tour=1');
    await screen.findByRole('heading', { name: '지도 움직이기' });
    const params = new URLSearchParams(router.state.location.search);
    expect([...params.keys()].sort()).toEqual(['mode', 'tour']);
  });
  it('이미 열린 5단계에서 다시 보기해도 경로와 상세를 정리하고 처음부터 시작한다', async () => {
    const router = setup('/?mode=all&tour=1');
    await screen.findByRole('heading', { name: '지도 움직이기' });
    await act(async () => {
      useGraphUiStore.getState().setTutorialStep(5);
      await router.navigate(
        '/?mode=all&tour=1&path=KRX:005930,NASDAQ:NVDA&select=node:KRX:005930',
      );
    });
    await userEvent.click(
      screen.getByRole('button', { name: '튜토리얼 다시 보기' }),
    );
    await screen.findByRole('heading', { name: '지도 움직이기' });
    expect(router.state.location.search).toBe('?mode=all&tour=1');
    expect(
      screen.queryByRole('complementary', { name: '두 기업 사이 경로' }),
    ).toBeNull();
  });
  it('같은 계정의 재진입도 선택·경로·과거 pin과 열린 근거/AI를 정리한다', async () => {
    member();
    const session = useAuthStore.getState().session!;
    useAuthStore.setState({
      session: {
        ...session,
        setup: { completed: true, tutorialCompleted: true },
      },
    });
    vi.mocked(getGraph).mockImplementation(async (request) =>
      createMockGraph(request),
    );
    const router = setup('/?mode=all');
    await screen.findByTestId('graph-canvas');
    useGraphUiStore.getState().openEvidence({
      kind: 'issue',
      id: 'old',
      label: 'old',
      evidenceIds: [],
    });
    useAiChatStore.getState().open();
    await act(async () => {
      await router.navigate(
        '/?mode=personal&tour=1&path=KRX:005930,NASDAQ:NVDA&select=node:KRX:005930&impact=KRX:005930,mock-issue-1&companyId=KRX:005930&event=old&asOf=2020-01-01T00:00:00Z&graphVersion=old&round=old&focus=old&hops=2',
      );
    });
    await screen.findByRole('heading', { name: '지도 움직이기' });
    expect(router.state.location.search).toBe('?mode=all&tour=1');
    expect(useGraphUiStore.getState().evidenceTarget).toBeNull();
    expect(useAiChatStore.getState().isOpen).toBe(false);
    expect(
      screen.queryByRole('complementary', { name: '두 기업 사이 경로' }),
    ).toBeNull();
    await userEvent.click(
      screen.getByRole('button', { name: '지도 이동 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '지도 확대 실습' }),
    );
    expect(screen.getByText('튜토리얼 2/5')).toBeTruthy();
  });

  it('튜토리얼 조회 맥락은 URL의 과거 pin 대신 표시된 현재 지도에서 가져온다', async () => {
    const spy = vi.spyOn(impactApi, 'getCompanyIssueImpact');
    const companySpy = vi.spyOn(companyDataHook, 'useCompanyData');
    const evidenceSpy = vi.spyOn(evidenceApi, 'getEvidence');
    const router = setup(
      '/?mode=all&tour=1&round=old&asOf=2020-01-01T00:00:00Z&graphVersion=old',
    );
    await userEvent.click(
      await screen.findByRole('button', { name: '지도 이동 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '지도 확대 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '삼성전자 선택' }),
    );
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { tutorialTarget } =
      await import('@/components/graph/tutorial/tutorial-target');
    const target = tutorialTarget(graph, true)!;
    // Even a stale pin inserted while the tutorial is already active cannot change its snapshot.
    await act(async () => {
      await router.navigate(
        `${router.state.location.search}&round=old&asOf=2020-01-01T00:00:00Z&graphVersion=old`,
      );
    });
    await userEvent.click(
      screen.getByRole('button', { name: `${target.issue.label} 선택` }),
    );
    await screen.findByText('튜토리얼 4/5');
    expect(spy).toHaveBeenLastCalledWith(target.company.id, target.issue.id, {
      round: undefined,
      asOf: graph.metadata.asOf,
      graphVersion: graph.metadata.graphVersion,
    });
    expect(companySpy.mock.calls.at(-1)?.[3]).toEqual({
      asOf: graph.metadata.asOf,
      graphVersion: graph.metadata.graphVersion,
    });
    await userEvent.click(
      screen.getAllByRole('button', { name: /근거 .*건 보기/ })[0],
    );
    await waitFor(() =>
      expect(evidenceSpy).toHaveBeenCalledWith(expect.any(String), {
        round: undefined,
        asOf: graph.metadata.asOf,
        graphVersion: graph.metadata.graphVersion,
      }),
    );
  });

  it('3단계 부분 응답 재조회 후 같은 상세 사건 버튼을 복원하고 다음 단계로 진행한다', async () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const partial = {
      ...graph,
      metadata: { ...graph.metadata, partial: true },
    };
    vi.mocked(getGraph).mockResolvedValue(partial);
    const router = setup('/?mode=all&tour=1');
    await userEvent.click(
      await screen.findByRole('button', { name: '지도 이동 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '지도 확대 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '삼성전자 선택' }),
    );
    const panel = await screen.findByRole('complementary', {
      name: '삼성전자 기업 상세',
    });
    const issue = await within(panel).findByRole('button', {
      name: /^HBM4 공급 계약/,
    });
    await waitFor(() =>
      expect((issue as HTMLButtonElement).disabled).toBe(false),
    );
    let finish!: (value: GraphResponse) => void;
    vi.mocked(getGraph).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await waitFor(() => {
      expect(issue.getAttribute('data-tutorial-action')).toBeNull();
      expect((issue as HTMLButtonElement).disabled).toBe(true);
      expect(issue.getAttribute('tabindex')).toBe('-1');
    });
    expect(screen.getByText('튜토리얼 3/5')).toBeTruthy();
    await act(async () => finish(partial));
    await waitFor(() => {
      expect(
        within(panel).getByRole('button', { name: /^HBM4 공급 계약/ }),
      ).toBe(issue);
      expect(issue.getAttribute('data-tutorial-action')).toBe('issue');
      expect((issue as HTMLButtonElement).disabled).toBe(false);
      expect(issue.getAttribute('aria-disabled')).toBeNull();
      expect(issue.getAttribute('tabindex')).toBeNull();
    });
    issue.focus();
    expect(document.activeElement).toBe(issue);
    await userEvent.click(issue);
    await screen.findByText('튜토리얼 4/5');
    expect(
      new URLSearchParams(router.state.location.search).get('impact'),
    ).toBe('KRX:005930,mock-issue-1');
  });

  it.each(['error', 'partial', 'no-target'] as const)(
    '%s 상태에서 실제 지도 재시도를 허용한다',
    async (scenario) => {
      const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
      if (scenario === 'error')
        vi.mocked(getGraph).mockRejectedValueOnce(
          new Error('retry-map-offline'),
        );
      else
        vi.mocked(getGraph).mockResolvedValueOnce(
          scenario === 'partial'
            ? { ...graph, metadata: { ...graph.metadata, partial: true } }
            : { ...graph, nodes: [], edges: [] },
        );
      setup('/?mode=all&tour=1');
      const retry =
        scenario === 'no-target'
          ? await screen.findByRole('button', { name: '지도 다시 불러오기' })
          : await screen.findByRole('button', { name: '다시 시도' });
      expect((retry as HTMLButtonElement).disabled).toBe(false);
      const count = vi.mocked(getGraph).mock.calls.length;
      await userEvent.click(retry);
      await waitFor(() =>
        expect(vi.mocked(getGraph).mock.calls.length).toBeGreaterThan(count),
      );
    },
  );
  beforeEach(() => {
    useGraphUiStore.getState().reset();
    anonymous();
    vi.mocked(getGraph).mockImplementation(async (request) =>
      createMockGraph(request),
    );
    vi.mocked(setTutorialCompleted).mockReset();
  });

  it('버튼으로 단계를 넘기지 못하고 비회원은 저장 없이 건너뛴다', async () => {
    const router = setup('/?mode=all&tour=1');
    expect(
      await screen.findByRole('heading', { name: '지도 움직이기' }),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: '다음' })).toBeNull();
    expect(screen.queryByRole('button', { name: '이전' })).toBeNull();
    await userEvent.click(
      screen.getByRole('button', { name: '튜토리얼 건너뛰기' }),
    );
    await waitFor(() =>
      expect(
        new URLSearchParams(router.state.location.search).has('tour'),
      ).toBe(false),
    );
    expect(setTutorialCompleted).not.toHaveBeenCalled();
  });

  it('FS015: 튜토리얼을 마치지 않은 회원은 지도에 들어오면 자동으로 열고, 마친 회원은 열지 않는다', async () => {
    member();
    const router = setup('/?mode=all');
    expect(
      await screen.findByRole('heading', { name: '지도 움직이기' }),
    ).toBeTruthy();
    expect(new URLSearchParams(router.state.location.search).get('tour')).toBe(
      '1',
    );
  });

  it('튜토리얼을 마친 회원에게는 자동으로 열지 않는다', async () => {
    member();
    const session = useAuthStore.getState().session!;
    useAuthStore.setState({
      session: {
        ...session,
        setup: { completed: true, tutorialCompleted: true },
      },
    });
    const router = setup('/?mode=all');
    await screen.findByTestId('graph-canvas');
    expect(screen.queryByRole('heading', { name: '지도 움직이기' })).toBeNull();
    expect(new URLSearchParams(router.state.location.search).has('tour')).toBe(
      false,
    );
  });

  it('같은 지도에서 회원이 바뀌면 새 회원의 미완료 튜토리얼을 연다', async () => {
    member();
    const router = setup('/?mode=all');
    await screen.findByRole('heading', { name: '지도 움직이기' });
    await router.navigate('/?mode=all');
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: '지도 움직이기' }),
      ).toBeNull(),
    );

    useAuthStore.getState().setSession({
      authenticated: true,
      kind: 'member',
      user: {
        id: 'member-2',
        email: 'member-2@zoop.test',
        displayName: '새 회원',
      },
      setup: { completed: true, tutorialCompleted: false },
      csrfToken: 'csrf-2',
      expiresAt: null,
    });

    expect(
      await screen.findByRole('heading', { name: '지도 움직이기' }),
    ).toBeTruthy();
    expect(new URLSearchParams(router.state.location.search).get('tour')).toBe(
      '1',
    );
  });

  it.each(['all', 'holdings', 'watchlist'])(
    '회원의 개인 %s 필터로 들어와도 전체 그래프로만 튜토리얼을 진행한다',
    async (scope) => {
      member();
      setup(`/?mode=personal&scope=${scope}&companyId=NASDAQ%3ANVDA&tour=1`);
      await screen.findByTestId('graph-canvas');
      expect(
        vi
          .mocked(getGraph)
          .mock.calls.every(
            ([request]) =>
              request.mode === 'all' && request.companyId === undefined,
          ),
      ).toBe(true);
      expect(screen.getByText(/실제 시장 전체 지도/)).toBeTruthy();
    },
  );

  it('비회원도 개인 종목 조회 없이 같은 전체 그래프로 시작한다', async () => {
    setup('/?mode=personal&scope=holdings&tour=1');
    await screen.findByTestId('graph-canvas');
    expect(
      vi
        .mocked(getGraph)
        .mock.calls.every(
          ([request]) =>
            request.mode === 'all' && request.companyId === undefined,
        ),
    ).toBe(true);
  });

  it('전체 그래프 조회 실패 시 개인 그래프로 바꾸지 않고 오류를 유지한다', async () => {
    member();
    vi.mocked(getGraph).mockRejectedValue(new Error('market-source-offline'));
    setup('/?mode=personal&tour=1');
    await screen.findByText(/market-source-offline/);
    expect(
      vi
        .mocked(getGraph)
        .mock.calls.every(([request]) => request.mode === 'all'),
    ).toBe(true);
    expect(screen.queryByRole('button', { name: '다음' })).toBeNull();
  });

  it('확대만 하거나 다른 기업을 눌러 단계 완료를 우회할 수 없다', async () => {
    member();
    setup('/?mode=all&tour=1');
    await userEvent.click(
      await screen.findByRole('button', { name: '지도 확대 실습' }),
    );
    expect(screen.getByText('튜토리얼 1/5')).toBeTruthy();
    await userEvent.click(
      screen.getByRole('button', { name: '지도 이동 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '지도 확대 실습' }),
    );
    const { tutorialTarget } =
      await import('@/components/graph/tutorial/tutorial-target');
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const target = tutorialTarget(data, true)!;
    const other = data.nodes.find(
      (node) => node.kind === 'company' && node.id !== target.company.id,
    )!;
    await userEvent.click(
      screen.getByRole('button', { name: `${other.label} 선택` }),
    );
    expect(screen.getByText('튜토리얼 2/5')).toBeTruthy();
  });

  it('3단계는 지도 위 실제 사건을 강조하고 클릭하면 영향 경로 성공 후 4단계로 진행한다', async () => {
    anonymous();
    const router = setup('/?mode=all&tour=1');
    await userEvent.click(
      await screen.findByRole('button', { name: '지도 이동 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '지도 확대 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '삼성전자 선택' }),
    );
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { tutorialTarget } =
      await import('@/components/graph/tutorial/tutorial-target');
    const target = tutorialTarget(graph, true)!;
    expect(
      screen.getByTestId('graph-canvas').getAttribute('data-tutorial-target'),
    ).toBe(target.issue.id);
    const other = graph.nodes.find(
      (node) => node.kind === 'issue' && node.id !== target.issue.id,
    )!;
    await userEvent.click(
      screen.getByRole('button', { name: `${other.label} 선택` }),
    );
    expect(screen.getByText('튜토리얼 3/5')).toBeTruthy();
    await userEvent.click(
      screen.getByRole('button', { name: `${target.issue.label} 선택` }),
    );
    await screen.findByText('튜토리얼 4/5');
    expect(
      new URLSearchParams(router.state.location.search).get('impact'),
    ).toBe(`${target.company.id},${target.issue.id}`);
  });

  it.each(['impact', 'evidence'] as const)(
    '%s 조회 실패는 다음 단계로 진행하지 않는다',
    async (failure) => {
      member();
      const spy =
        failure === 'impact'
          ? vi
              .spyOn(impactApi, 'getCompanyIssueImpact')
              .mockRejectedValue(new Error('tutorial-impact-offline'))
          : vi
              .spyOn(evidenceApi, 'getEvidence')
              .mockRejectedValue(new Error('tutorial-evidence-offline'));
      try {
        setup('/?mode=personal&tour=1');
        await userEvent.click(
          await screen.findByRole('button', { name: '지도 이동 실습' }),
        );
        await userEvent.click(
          screen.getByRole('button', { name: '지도 확대 실습' }),
        );
        const { tutorialTarget } =
          await import('@/components/graph/tutorial/tutorial-target');
        const target = tutorialTarget(
          createMockGraph({ mode: 'all', personalFilter: 'all' }),
          true,
        )!;
        await userEvent.click(
          screen.getByRole('button', { name: `${target.company.label} 선택` }),
        );
        const panel = await screen.findByRole('complementary', {
          name: `${target.company.label} 기업 상세`,
        });
        await userEvent.click(
          await within(panel).findByRole('button', {
            name: new RegExp(target.issue.label),
          }),
        );
        if (failure === 'impact') {
          await screen.findByText('tutorial-impact-offline');
          expect(screen.getByText('튜토리얼 3/5')).toBeTruthy();
        } else {
          await screen.findByText('튜토리얼 4/5');
          const path = screen.getByRole('complementary', { name: /영향 경로/ });
          await userEvent.click(
            (
              await within(path).findAllByRole('button', {
                name: /근거 .*건 보기/,
              })
            )[0],
          );
          await screen.findByText(/tutorial-evidence-offline/);
          expect(screen.getByText('튜토리얼 4/5')).toBeTruthy();
        }
        expect(setTutorialCompleted).not.toHaveBeenCalled();
      } finally {
        spy.mockRestore();
      }
    },
  );

  it('회원 완료는 상태 API 성공 후에만 화면을 닫는다', async () => {
    member();
    vi.mocked(setTutorialCompleted).mockResolvedValue(
      useAuthStore.getState().session!,
    );
    const router = setup('/?mode=all&tour=1');
    await screen.findByRole('heading', { name: '지도 움직이기' });
    await userEvent.click(
      await screen.findByRole('button', { name: '지도 이동 실습' }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '지도 확대 실습' }),
    );
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const { tutorialTarget } =
      await import('@/components/graph/tutorial/tutorial-target');
    const target = tutorialTarget(graph, true)!;
    await userEvent.click(
      screen.getByRole('button', { name: `${target.company.label} 선택` }),
    );
    await userEvent.click(
      await within(
        await screen.findByRole('complementary', {
          name: `${target.company.label} 기업 상세`,
        }),
      ).findByRole('button', {
        name: new RegExp(target.issue.label),
      }),
    );
    await screen.findByText('튜토리얼 4/5');
    const impactPanel = screen.getByRole('complementary', {
      name: /영향 경로/,
    });
    await userEvent.click(
      (
        await within(impactPanel).findAllByRole('button', {
          name: /근거 .*건 보기/,
        })
      )[0],
    );
    await screen.findByRole('heading', { name: '근거 문서' });
    await screen.findByText('튜토리얼 5/5');
    await userEvent.click(screen.getByRole('button', { name: '근거 창 닫기' }));
    expect(screen.getByRole('heading', { name: 'AI에게 묻기' })).toBeTruthy();
    expect(
      screen.queryByRole('button', { name: '튜토리얼 건너뛰기' }),
    ).toBeNull();
    const askAi = within(impactPanel).getByRole('button', {
      name: 'AI에게 묻기',
    });
    expect(askAi.classList.contains('tutorial-target')).toBe(true);
    useAiChatStore.getState().close();
    await userEvent.click(askAi);
    expect(useAiChatStore.getState().isOpen).toBe(false);
    await waitFor(() =>
      expect(setTutorialCompleted).toHaveBeenCalledWith(true),
    );
    await waitFor(() =>
      expect(
        new URLSearchParams(router.state.location.search).has('tour'),
      ).toBe(false),
    );
    // 저장 응답의 세션이 아직 미완료여도, 이번 방문에 연 튜토리얼을 다시 자동으로 열지 않는다.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(new URLSearchParams(router.state.location.search).has('tour')).toBe(
      false,
    );
    expect(screen.queryByRole('heading', { name: '지도 움직이기' })).toBeNull();
  });
});

describe('D-GRP-06 · 기업 영향 경로', () => {
  beforeEach(() => {
    anonymous();
    vi.mocked(getGraph).mockImplementation(async (request) =>
      createMockGraph(request),
    );
  });

  it('D-GRP-03 선택한 기업 패널을 키보드로 좌우 조절하고 너비를 저장한다', async () => {
    localStorage.removeItem('zoop:graph-company-panel-width');
    setup('/?mode=all&select=node%3AKRX%3A005930');
    const panel = await screen.findByRole('complementary', {
      name: '삼성전자 기업 상세',
    });
    const separator = screen.getByRole('separator', {
      name: '기업 패널 너비 조절',
    });
    expect(separator.getAttribute('aria-valuenow')).toBe('320');
    separator.focus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(separator.getAttribute('aria-valuenow')).toBe('336');
    expect((panel as HTMLElement).style.width).toBe('336px');
    expect(localStorage.getItem('zoop:graph-company-panel-width')).toBe('336');
    localStorage.removeItem('zoop:graph-company-panel-width');
  });

  it('기업의 직접 사건에서 URL 경로 패널을 열고 닫을 때 기업 선택을 보존한다', async () => {
    const router = setup();
    await userEvent.click(
      await screen.findByRole('button', { name: '삼성전자 선택' }),
    );
    const companyPanel = await screen.findByRole('complementary', {
      name: '삼성전자 기업 상세',
    });
    const issue = await within(companyPanel).findByRole('button', {
      name: /HBM4 공급 계약/,
    });
    await userEvent.click(issue);
    expect(
      await screen.findByRole('heading', { name: '삼성전자 · 영향 경로' }),
    ).toBeTruthy();
    const query = new URLSearchParams(router.state.location.search);
    expect(query.get('select')).toBe('node:KRX:005930');
    expect(query.get('impact')).toBe('KRX:005930,mock-issue-1');
    expect(
      await screen.findByRole('heading', { name: '확인된 연결' }),
    ).toBeTruthy();
    expect(await screen.findByText(/함께 연결된 기업 2곳/)).toBeTruthy();
    await userEvent.click(
      screen.getByRole('button', { name: '영향 경로 닫기' }),
    );
    expect(
      new URLSearchParams(router.state.location.search).get('select'),
    ).toBe('node:KRX:005930');
    expect(
      new URLSearchParams(router.state.location.search).has('impact'),
    ).toBe(false);
  });
});

describe('D-GRP-07b · 선택 기업 포커스', () => {
  beforeEach(() => {
    anonymous();
    vi.mocked(getGraph).mockImplementation(async (request) =>
      createMockGraph(request),
    );
  });

  it('1·2단계와 전체 보기 URL을 전환하고 상세 닫기와 포커스 해제를 구분한다', async () => {
    const router = setup('/?mode=all&select=node%3AKRX%3A005930');
    const panel = await screen.findByRole('complementary', {
      name: '삼성전자 기업 상세',
    });
    await userEvent.click(
      await within(panel).findByRole('button', {
        name: '기업 중심 그래프',
      }),
    );
    expect(
      await screen.findByRole('group', { name: '삼성전자 중심 보기' }),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole('radio', { name: '2단계: 이웃의 이웃까지' }),
    );
    expect(new URLSearchParams(router.state.location.search).get('hops')).toBe(
      '2',
    );
    await userEvent.click(
      screen.getByRole('button', { name: '기업 상세 닫기' }),
    );
    expect(new URLSearchParams(router.state.location.search).get('focus')).toBe(
      'KRX:005930',
    );
    await userEvent.click(screen.getByRole('button', { name: '전체 보기' }));
    expect(new URLSearchParams(router.state.location.search).has('focus')).toBe(
      false,
    );
  });

  it('그래프의 hop 범위는 정확히 인접 노드만 포함한다', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const one = focusNeighborhood(graph, 'KRX:005930', 1);
    const two = focusNeighborhood(graph, 'KRX:005930', 2);
    expect(one.has('KRX:005930')).toBe(true);
    expect(one.has('mock-issue-1')).toBe(true);
    expect(two.size).toBeGreaterThan(one.size);
  });
});

it('D-GRP-01/01b restores mode selection, consumes prefetched data once, and retains current state on failure', async () => {
  member();
  useAuthStore.setState((state) => ({
    session: state.session
      ? {
          ...state.session,
          setup: { completed: true, tutorialCompleted: true },
        }
      : null,
  }));
  vi.mocked(getGraph).mockImplementation(async (request) =>
    createMockGraph(request),
  );
  const router = setup('/?mode=all&select=node%3ANASDAQ%3ANVDA');
  await screen.findByTestId('graph-canvas');
  await userEvent.click(
    within(screen.getByLabelText('그래프 모드')).getByRole('button', {
      name: '내 종목',
    }),
  );
  await waitFor(() =>
    expect(new URLSearchParams(router.state.location.search).get('mode')).toBe(
      'personal',
    ),
  );
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('그래프 모드'))
        .getByRole('button', { name: '내 종목' })
        .getAttribute('aria-pressed'),
    ).toBe('true'),
  );
  await userEvent.click(screen.getByRole('button', { name: '시장 전체' }));
  await waitFor(() =>
    expect(
      new URLSearchParams(router.state.location.search).get('select'),
    ).toBe('node:NASDAQ:NVDA'),
  );
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('그래프 모드'))
        .getByRole('button', { name: '시장 전체' })
        .getAttribute('aria-pressed'),
    ).toBe('true'),
  );
  expect(vi.mocked(getGraph)).toHaveBeenCalledTimes(3);
  vi.mocked(getGraph).mockRejectedValueOnce(new Error('source offline'));
  await userEvent.click(
    within(screen.getByLabelText('그래프 모드')).getByRole('button', {
      name: '내 종목',
    }),
  );
  await screen.findByText(/지도 전환 실패/);
  expect(new URLSearchParams(router.state.location.search).get('mode')).toBe(
    'all',
  );
  expect(new URLSearchParams(router.state.location.search).get('select')).toBe(
    'node:NASDAQ:NVDA',
  );
});

it('D-GRP-05 15번 근거 강조는 보고 있던 중심 보기(1·2단계)를 풀지 않는다', async () => {
  anonymous();
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  vi.mocked(getGraph).mockResolvedValue(graph);
  vi.spyOn(evidenceApi, 'getEvidence').mockImplementation(async (id) =>
    createMockEvidence(id),
  );
  setup('/?mode=all&focus=mock-issue-1&hops=2');
  await screen.findByTestId('graph-canvas');
  act(() =>
    useGraphUiStore.getState().openEvidence({
      kind: 'issue',
      id: 'mock-issue-1',
      label: '사건',
      evidenceIds: ['mock-evidence-1'],
      mapContext: {
        graphVersion: graph.metadata.graphVersion ?? undefined,
        asOf: graph.metadata.asOf,
        url: '/',
      },
    }),
  );
  await userEvent.click(
    await screen.findByRole('button', { name: '◇ 지도에서 보기' }),
  );
  const canvas = screen.getByTestId('graph-canvas');
  expect(canvas.getAttribute('data-highlighted')).not.toBe('');
  expect(canvas.getAttribute('data-focus')).toBe('mock-issue-1');
  expect(canvas.getAttribute('data-hops')).toBe('2');
  vi.restoreAllMocks();
});

it('D-GRP-05 15번 근거가 중심 보기 밖이면 강조하는 동안만 전체 지도로 보이고, 창을 닫으면 중심 보기로 돌아온다', async () => {
  anonymous();
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const evidenceNodes = graph.edges
    .filter((edge) => edge.evidenceIds.includes('mock-evidence-1'))
    .flatMap((edge) => [edge.source, edge.target]);
  const outside = graph.nodes.find((node) => {
    const shown = focusNeighborhood(graph, node.id, 1);
    return evidenceNodes.some((id) => !shown.has(id));
  });
  expect(outside).toBeTruthy();
  vi.mocked(getGraph).mockResolvedValue(graph);
  vi.spyOn(evidenceApi, 'getEvidence').mockImplementation(async (id) =>
    createMockEvidence(id),
  );
  setup(`/?mode=all&focus=${encodeURIComponent(outside!.id)}&hops=1`);
  await screen.findByTestId('graph-canvas');
  act(() =>
    useGraphUiStore.getState().openEvidence({
      kind: 'issue',
      id: 'mock-issue-1',
      label: '사건',
      evidenceIds: ['mock-evidence-1'],
      mapContext: {
        graphVersion: graph.metadata.graphVersion ?? undefined,
        asOf: graph.metadata.asOf,
        url: '/',
      },
    }),
  );
  await userEvent.click(
    await screen.findByRole('button', { name: '◇ 지도에서 보기' }),
  );
  const canvas = screen.getByTestId('graph-canvas');
  expect(canvas.getAttribute('data-highlighted')).not.toBe('');
  expect(canvas.getAttribute('data-focus')).toBe('');
  expect(canvas.getAttribute('data-center')).toBe(evidenceNodes[0]);
  expect(screen.queryByText(/지도에 없어요/)).toBeNull();

  await userEvent.click(screen.getByRole('button', { name: '근거 창 닫기' }));
  expect(screen.getByTestId('graph-canvas').getAttribute('data-focus')).toBe(
    outside!.id,
  );
  expect(
    screen.getByTestId('graph-canvas').getAttribute('data-highlighted'),
  ).toBe('');
  vi.restoreAllMocks();
});

it('D-GRP-05 15번 근거 창을 닫았다 같은 대상으로 다시 열면 예전 강조가 살아나지 않는다', async () => {
  anonymous();
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  vi.mocked(getGraph).mockResolvedValue(graph);
  vi.spyOn(evidenceApi, 'getEvidence').mockImplementation(async (id) =>
    createMockEvidence(id),
  );
  setup();
  await screen.findByTestId('graph-canvas');
  const target = {
    kind: 'issue' as const,
    id: 'mock-issue-1',
    label: '사건',
    evidenceIds: ['mock-evidence-1'],
    mapContext: {
      graphVersion: graph.metadata.graphVersion ?? undefined,
      asOf: graph.metadata.asOf,
      url: '/',
    },
  };
  act(() => useGraphUiStore.getState().openEvidence(target));
  await userEvent.click(
    await screen.findByRole('button', { name: '◇ 지도에서 보기' }),
  );
  expect(
    screen.getByTestId('graph-canvas').getAttribute('data-highlighted'),
  ).not.toBe('');
  act(() => useGraphUiStore.getState().closeEvidence());
  act(() => useGraphUiStore.getState().openEvidence(target));
  await screen.findByRole('button', { name: '◇ 지도에서 보기' });
  expect(
    screen.getByTestId('graph-canvas').getAttribute('data-highlighted'),
  ).toBe('');
  vi.restoreAllMocks();
});
