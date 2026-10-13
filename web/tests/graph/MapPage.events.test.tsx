import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MapPage from '@/pages/map/MapPage';
import { getEvent } from '@/apis/graph/events';
import { getGraph } from '@/apis/graph/graph';
import { createMockEvent } from '@/mocks/events/fixture';
import { createMockGraph } from '@/mocks/graph/response';
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
  }: {
    data: GraphResponse;
    selectedId: string | null;
    onSelect: (id: string) => void;
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
  useAuthStore.setState({ accessToken: null });
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
      screen.getByRole('button', { name: '근거 1건 보기' }),
    );
    expect(useGraphUiStore.getState().evidenceTarget).toMatchObject({
      kind: 'issue',
      id: 'mock-issue-1',
      evidenceIds: ['mock-evidence-1'],
      mapContext: {
        graphVersion: 'mock-graph-v1',
        asOf: '2026-10-06T03:41:00Z',
        url: '/?mode=all&scope=watchlist&select=node%3Amock-issue-1',
      },
    });
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
