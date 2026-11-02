import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MapPage from '@/pages/map/MapPage';
import { getGraph } from '@/apis/graph/graph';
import { createMockGraph } from '@/mocks/graph/response';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import type { AnswerMapTarget } from '@/components/ai/ChatJobCard';

// D-AI-02 → D-GRP-04: 답변의 관계 대상이 지도에서 실제로 열리는지. 그리기는 따로 검증하므로 대체한다.
vi.mock('@/apis/graph/graph', () => ({ getGraph: vi.fn() }));
vi.mock('@/components/graph/GraphCanvas', () => ({
  default: () => <div data-testid="graph-canvas" />,
}));

let viewOnMap: (target: AnswerMapTarget) => boolean = () => false;
vi.mock('@/components/ai/AiChatDrawer', () => ({
  default: ({
    onViewOnMap,
  }: {
    onViewOnMap: (target: AnswerMapTarget) => boolean;
  }) => {
    viewOnMap = onViewOnMap;
    return null;
  },
}));

beforeEach(() => {
  vi.mocked(getGraph)
    .mockReset()
    .mockImplementation(async (request) => createMockGraph(request));
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

async function setup() {
  const router = createMemoryRouter([{ path: '/', element: <MapPage /> }], {
    initialEntries: ['/?mode=all'],
  });
  render(<RouterProvider router={router} />);
  await screen.findByTestId('graph-canvas');
  const graph = createMockGraph({
    mode: 'all',
    personalFilter: 'all',
  });
  return { router, graph };
}

describe('D-AI-02 · an answer opens its relation on the map', () => {
  it('selects the edge when the map shows the same snapshot', async () => {
    const { router, graph } = await setup();
    const edge = graph.edges[0];

    const opened = viewOnMap({
      id: edge.id,
      kind: 'edge',
      graphVersion: graph.metadata.graphVersion,
      asOf: null,
    });

    expect(opened).toBe(true);
    await vi.waitFor(() =>
      expect(
        new URLSearchParams(router.state.location.search).get('select'),
      ).toBe(`edge:${edge.id}`),
    );
  });

  it('refuses an edge the map does not have or another snapshot', async () => {
    const { router, graph } = await setup();
    const before = router.state.location.search;

    expect(
      viewOnMap({
        id: 'edge-not-on-this-map',
        kind: 'edge',
        graphVersion: graph.metadata.graphVersion,
        asOf: null,
      }),
    ).toBe(false);
    expect(
      viewOnMap({
        id: graph.edges[0].id,
        kind: 'edge',
        graphVersion: 'another-version',
        asOf: null,
      }),
    ).toBe(false);
    expect(router.state.location.search).toBe(before);
  });
});
