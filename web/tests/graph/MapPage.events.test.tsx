import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MapPage from '@/pages/map/MapPage';
import { getEvent } from '@/apis/graph/events';
import { getGraph } from '@/apis/graph/graph';
import { RoundGraphUnavailableError } from '@/apis/graph/round-graph-error';
import { createMockEvent } from '@/mocks/events/fixture';
import { createMockGraph } from '@/mocks/graph/response';
import { createMockRelation } from '@/mocks/relations/fixture';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { useAuthStore } from '@/stores/useAuthStore';
import type { GraphResponse } from '@/types/map/graph';

vi.mock('@/apis/graph/events', async (original) => ({
  ...(await original<typeof import('@/apis/graph/events')>()),
  getEvent: vi.fn(),
}));
vi.mock('@/apis/graph/graph', () => ({ getGraph: vi.fn() }));
// Canvas rendering is verified separately; these tests exercise actual routing,
// data hooks, panel, handoff stores and focus restoration together.
vi.mock('@/components/graph/GraphCanvas', () => ({
  default: ({
    data,
    selectedId,
    onSelect,
    onSelectEdge,
  }: {
    data: GraphResponse;
    selectedId: string | null;
    onSelect: (id: string) => void;
    onSelectEdge: (id: string) => void;
  }) => (
    <div data-testid="graph-canvas">
      {data.nodes.map((node) => (
        <button
          key={node.id}
          onClick={() => onSelect(node.id)}
          aria-pressed={selectedId === node.id}
        >
          {node.label} 선택
        </button>
      ))}
      <button
        onClick={() =>
          onSelectEdge(
            data.edges.find((edge) => edge.relationType === 'SHARES_ISSUE')!.id,
          )
        }
      >
        사건 공유 연결선 선택
      </button>
    </div>
  ),
}));

beforeEach(() => {
  vi.mocked(getGraph)
    .mockReset()
    .mockImplementation(async (request) => createMockGraph(request));
  vi.mocked(getEvent)
    .mockReset()
    .mockImplementation(async (id) => createMockEvent(id));
  useGraphUiStore.getState().reset();
  useAiChatStore.getState().reset();
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
});
function setup(url = '/?mode=all&scope=watchlist') {
  const router = createMemoryRouter([{ path: '/', element: <MapPage /> }], {
    initialEntries: [url],
  });
  render(<RouterProvider router={router} />);
  return router;
}

describe('D-GRP-02 · map selection and downstream context', () => {
  it('opens by node selection; closing and Back preserve graph, mode and filter', async () => {
    const router = setup();
    const button = await screen.findByRole('button', {
      name: 'HBM4 공급 계약 선택',
    });
    const canvas = screen.getByTestId('graph-canvas');
    await userEvent.click(button);
    await screen.findByRole('heading', { name: 'HBM4 공급 계약' });
    expect(
      new URLSearchParams(router.state.location.search).get('select'),
    ).toBe('node:mock-issue-1');
    await userEvent.click(screen.getByRole('button', { name: '상세 닫기' }));
    expect(router.state.location.search).toBe('?mode=all&scope=watchlist');
    expect(document.activeElement).toBe(button);
    await userEvent.click(button);
    await screen.findByRole('heading', { name: 'HBM4 공급 계약' });
    await act(async () => {
      await router.navigate(-1);
    });
    expect(screen.queryByRole('complementary')).toBeNull();
    expect(router.state.location.search).toBe('?mode=all&scope=watchlist');
    expect(screen.getByTestId('graph-canvas')).toBe(canvas);
    expect(getGraph).toHaveBeenCalledTimes(1);
  });
  it('supports direct URLs and sends response version, event and map context to all actions', async () => {
    const router = setup(
      '/?mode=all&scope=watchlist&select=node%3Amock-issue-1',
    );
    await screen.findByRole('heading', { name: 'HBM4 공급 계약' });
    await userEvent.click(
      screen.getByRole('button', { name: '근거 2건 보기' }),
    );
    expect(useGraphUiStore.getState().evidenceTarget).toMatchObject({
      kind: 'issue',
      id: 'mock-issue-1',
      evidenceIds: ['mock-evidence-1', 'mock-evidence-1-detail'],
      mapContext: {
        graphVersion: 'mock-graph-v1',
        asOf: '2026-10-06T03:41:00Z',
        url: '/?mode=all&scope=watchlist&select=node%3Amock-issue-1',
      },
    });
    await userEvent.click(screen.getByRole('button', { name: '근거 창 닫기' }));
    await userEvent.click(screen.getByRole('button', { name: 'AI에게 묻기' }));
    expect(useAiChatStore.getState()).toMatchObject({
      isOpen: true,
      context: {
        kind: 'issue',
        id: 'mock-issue-1',
        mapContext: { graphVersion: 'mock-graph-v1' },
      },
    });
    await userEvent.click(
      screen.getByRole('button', { name: '이 노드 중심으로 보기' }),
    );
    expect(new URLSearchParams(router.state.location.search).get('focus')).toBe(
      'mock-issue-1',
    );
    expect(new URLSearchParams(router.state.location.search).get('hops')).toBe(
      '1',
    );
    await userEvent.click(screen.getByRole('button', { name: '상세 닫기' }));
    expect(new URLSearchParams(router.state.location.search).get('focus')).toBe(
      'mock-issue-1',
    );
  });
  it('keeps the current graph on detail failure and loads the latest selection on retry', async () => {
    vi.mocked(getEvent)
      .mockRejectedValueOnce(new Error('상세 오류'))
      .mockImplementation(async (id) => createMockEvent(id));
    setup();
    await userEvent.click(
      await screen.findByRole('button', { name: 'HBM4 공급 계약 선택' }),
    );
    await screen.findByRole('alert');
    expect(screen.getByTestId('graph-canvas')).toBeTruthy();
    await userEvent.click(
      screen.getByRole('button', { name: 'HBM3E 12단 경쟁 선택' }),
    );
    await screen.findByRole('heading', { name: 'HBM3E 12단 경쟁' });
    expect(screen.queryByRole('alert')).toBeNull();
    await waitFor(() => expect(getGraph).toHaveBeenCalledTimes(1));
  });
});

describe('D-GRP-04 · map navigation and evidence handoff', () => {
  it('selects an edge, opens all/per-issue evidence, keeps URL, and restores opener on close/Back', async () => {
    const router = setup();
    const opener = await screen.findByRole('button', {
      name: '사건 공유 연결선 선택',
    });
    const canvas = screen.getByTestId('graph-canvas');
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const edge = graph.edges.find(
      (item) => item.relationType === 'SHARES_ISSUE',
    )!;
    const detail = createMockRelation(edge.id);
    await userEvent.click(opener);
    const panel = await screen.findByRole('complementary', {
      name: `${detail.source.label} – ${detail.target.label}`,
    });
    const originalUrl = router.state.location.search;
    const actions = within(panel).getAllByRole('button', {
      name: /근거 .*건 보기/,
    });
    await userEvent.click(actions[0]);
    expect(useGraphUiStore.getState().evidenceTarget).toMatchObject({
      kind: 'edge',
      id: edge.id,
      evidenceIds: detail.evidenceIds,
      verifiedAt: null,
      mapContext: { graphVersion: 'mock-graph-v1', url: `/${originalUrl}` },
    });
    await screen.findByRole('dialog', { name: '근거 문서' });
    await userEvent.click(screen.getByRole('button', { name: '근거 창 닫기' }));
    expect(router.state.location.search).toBe(originalUrl);
    expect(document.activeElement).toBe(actions[0]);
    await userEvent.click(actions[1]);
    expect(useGraphUiStore.getState().evidenceTarget).toMatchObject({
      kind: 'issue',
      id: detail.via[0].id,
      evidenceIds: detail.via[0].evidenceIds,
    });
    await userEvent.click(screen.getByRole('button', { name: '근거 창 닫기' }));
    await userEvent.click(screen.getByRole('button', { name: 'AI에게 묻기' }));
    expect(useAiChatStore.getState().context).toMatchObject({
      kind: 'edge',
      id: edge.id,
    });
    await userEvent.click(screen.getByRole('button', { name: '상세 닫기' }));
    expect(router.state.location.search).toBe('?mode=all&scope=watchlist');
    expect(document.activeElement).toBe(opener);
    await act(async () => {
      await router.navigate(-1);
    });
    await screen.findByRole('complementary', {
      name: `${detail.source.label} – ${detail.target.label}`,
    });
    expect(screen.getByTestId('graph-canvas')).toBe(canvas);
    expect(getGraph).toHaveBeenCalledTimes(1);
  });
  it('opens shared relations from the company related-company list', async () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const edge = graph.edges.find(
      (item) => item.relationType === 'SHARES_ISSUE',
    )!;
    const detail = createMockRelation(edge.id);
    const router = setup(
      `/?mode=all&select=${encodeURIComponent(`node:${edge.source}`)}`,
    );
    const companyPanel = await screen.findByRole('complementary', {
      name: `${detail.source.label} 기업 상세`,
    });
    const relatedButton = await within(companyPanel).findByRole('button', {
      name: new RegExp(`${detail.target.label}.*공유 사건`),
    });
    await userEvent.click(relatedButton);
    await screen.findByRole('complementary', {
      name: `${detail.source.label} – ${detail.target.label}`,
    });
    expect(
      new URLSearchParams(router.state.location.search).get('select'),
    ).toBe(`edge:${edge.id}`);
  });
});

describe('D-BRF-04 · round map that is not provided', () => {
  it('shows a not-provided notice instead of a failure and retry', async () => {
    vi.mocked(getGraph).mockRejectedValue(
      new RoundGraphUnavailableError(
        '발행 당시 고정 그래프 조회가 아직 연결되지 않았습니다.',
      ),
    );
    setup('/?round=brf-2026-10-15-evening');
    expect(
      await screen.findByText('이 회차의 관계 지도는 아직 제공하지 않아요.'),
    ).toBeTruthy();
    expect(screen.queryByText('관계 지도를 불러오지 못했습니다.')).toBeNull();
    expect(screen.queryByText(/조회 실패/)).toBeNull();
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull();
  });

  it('keeps the not-provided notice without retry in the company path panel of a round link', async () => {
    vi.mocked(getGraph).mockRejectedValue(
      new RoundGraphUnavailableError(
        '발행 당시 고정 그래프 조회가 아직 연결되지 않았습니다.',
      ),
    );
    setup('/?round=brf-2026-10-15-evening&path=KRX:005930,KRX:000660');
    expect(
      (
        await screen.findAllByText(
          '이 회차의 관계 지도는 아직 제공하지 않아요.',
        )
      ).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText('그래프 조회 실패')).toBeNull();
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull();
  });

  it('keeps the failure and retry for a round map that failed to load', async () => {
    vi.mocked(getGraph).mockRejectedValue(new Error('네트워크 오류'));
    setup('/?round=brf-2026-10-15-evening');
    expect(
      await screen.findByText('관계 지도를 불러오지 못했습니다.'),
    ).toBeTruthy();
    expect(screen.getByText(/조회 실패: 네트워크 오류/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy();
  });
});
