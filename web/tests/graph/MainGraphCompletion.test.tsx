import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MapPage from '@/pages/map/MapPage';
import { getGraph } from '@/apis/graph/graph';
import { getBriefingGraphBasis } from '@/apis/briefing/briefing';
import { setTutorialCompleted } from '@/apis/graph/tutorial';
import { focusNeighborhood } from '@/components/graph/graph-model';
import { createMockGraph } from '@/mocks/graph/response';
import { useAuthStore } from '@/stores/useAuthStore';
import type { GraphResponse } from '@/types/map/graph';

vi.mock('@/apis/graph/graph', () => ({ getGraph: vi.fn() }));
vi.mock('@/apis/briefing/briefing', () => ({ getBriefingGraphBasis: vi.fn() }));
vi.mock('@/apis/graph/tutorial', () => ({ setTutorialCompleted: vi.fn() }));
vi.mock('@/components/graph/GraphCanvas', () => ({
  default: ({
    data,
    selectedId,
    focusId,
    focusHops,
    onSelect,
  }: {
    data: GraphResponse;
    selectedId: string | null;
    focusId: string | null;
    focusHops: 1 | 2;
    onSelect: (id: string) => void;
  }) => (
    <div
      data-testid="graph-canvas"
      data-focus={focusId ?? ''}
      data-hops={focusHops}
    >
      {data.nodes.map((node) => (
        <button
          key={node.id}
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

describe('D-GRP-T~T5 · 관계 그래프 튜토리얼', () => {
  beforeEach(() => {
    anonymous();
    vi.mocked(getGraph).mockImplementation(async (request) =>
      createMockGraph(request),
    );
    vi.mocked(setTutorialCompleted).mockReset();
  });

  it('5단계를 왕복하고 비회원은 저장 없이 건너뛴다', async () => {
    const router = setup('/?mode=all&tour=1');
    expect(
      await screen.findByRole('heading', { name: '지도 움직이기' }),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(
      screen.getByRole('heading', { name: '기업이나 사건 고르기' }),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '이전' }));
    expect(screen.getByText('튜토리얼 1/5')).toBeTruthy();
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

  it('회원 완료는 상태 API 성공 후에만 화면을 닫는다', async () => {
    member();
    vi.mocked(setTutorialCompleted).mockResolvedValue(
      useAuthStore.getState().session!,
    );
    const router = setup('/?mode=all&tour=1');
    await screen.findByRole('heading', { name: '지도 움직이기' });
    for (let step = 1; step < 5; step += 1)
      await userEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(screen.getByRole('heading', { name: 'AI에게 묻기' })).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '마치기' }));
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
        name: '이 기업 중심으로 보기',
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
