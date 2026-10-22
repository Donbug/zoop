import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MapPage from '@/pages/map/MapPage';
import * as impactApi from '@/apis/graph/impact';
import * as evidenceApi from '@/apis/evidence/evidence';
import { getGraph } from '@/apis/graph/graph';
import { getBriefingGraphBasis } from '@/apis/briefing/briefing';
import { setTutorialCompleted } from '@/apis/graph/tutorial';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import { useAiChatStore } from '@/stores/useAiChatStore';
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
    onTutorialAction,
    tutorialTargetId,
  }: {
    tutorialTargetId?: string;
    onTutorialAction?: (action: 'pan' | 'zoom') => void;
    data: GraphResponse;
    selectedId: string | null;
    focusId: string | null;
    focusHops: 1 | 2;
    onSelect: (id: string) => void;
  }) => (
    <div
      data-testid="graph-canvas"
      data-tutorial-target={tutorialTargetId}
      data-focus={focusId ?? ''}
      data-hops={focusHops}
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
