import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MapPage from '@/pages/map/MapPage';
import ChatJobCard, { type AnswerMapTarget } from '@/components/ai/ChatJobCard';
import { getGraph } from '@/apis/graph/graph';
import * as relationApi from '@/apis/graph/relations';
import { createMockGraph } from '@/mocks/graph/response';
import { createMockRelation } from '@/mocks/relations/fixture';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import type { ChatJob } from '@/types/ai';
import type { GraphResponse } from '@/types/map/graph';
import { deferred } from '../support/fakeServer';

// D-AI-02b → D-GRP-04: saved-answer actions use the graph that actually loads.
vi.mock('@/apis/graph/graph', () => ({ getGraph: vi.fn() }));
vi.mock('@/components/graph/GraphCanvas', () => ({
  default: () => <div data-testid="graph-canvas" />,
}));

let answerJob: ChatJob;
function unexpectedQuestionMutation() {
  throw new Error('This fixture only opens a saved answer on the map.');
}
vi.mock('@/components/ai/AiChatDrawer', () => ({
  default: function SavedAnswerDrawer({
    onViewOnMap,
  }: {
    onViewOnMap: (target: AnswerMapTarget) => boolean;
  }) {
    const isOpen = useAiChatStore((state) => state.isOpen);
    return isOpen ? (
      <ChatJobCard
        job={answerJob}
        busy={false}
        onChoose={unexpectedQuestionMutation}
        onAnswerFreely={unexpectedQuestionMutation}
        onRetry={unexpectedQuestionMutation}
        onViewOnMap={onViewOnMap}
      />
    ) : null;
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

function savedAnswer(target: AnswerMapTarget): ChatJob {
  const at = '2026-10-21T00:00:00Z';
  return {
    id: 'saved-answer-job',
    sessionId: 'saved-conversation',
    seq: 1,
    question: '이 관계를 지도에서 보여 주세요.',
    status: 'completed',
    phase: null,
    outcome: 'answered',
    askedAt: at,
    context: {
      items: [],
      evidenceCount: 0,
      period: null,
      asOf: target.asOf,
      graphVersion: target.graphVersion,
    },
    resolves: null,
    failure: null,
    result: {
      outcome: 'answered',
      messageId: 'saved-answer-message',
      answer: '저장된 관계 답변입니다.',
      sections: [],
      answerBasis: 'none',
      reason: null,
      sources: [],
      citations: [],
      graphTargets: [{ id: target.id, kind: target.kind }],
      applied: {
        companies: [],
        issues: [],
        period: null,
        graphVersion: target.graphVersion,
        dataAsOf: at,
        questionOverrodeContext: false,
      },
      choices: [],
      action: null,
      limitations: [],
      answerStatus: 'complete',
      notices: [],
      uiActions: [],
    },
    runs: 1,
    createdAt: at,
    updatedAt: at,
    finishedAt: at,
  };
}

async function setup(target: { id?: string; graphVersion?: string } = {}) {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const edge = graph.edges.find((item) => item.relationType === 'FOLLOWS')!;
  answerJob = savedAnswer({
    id: target.id ?? edge.id,
    kind: 'edge',
    graphVersion: target.graphVersion ?? graph.metadata.graphVersion,
    asOf: null,
  });
  useAiChatStore.getState().open(null);
  const router = createMemoryRouter([{ path: '/', element: <MapPage /> }], {
    initialEntries: ['/?mode=all'],
  });
  render(<RouterProvider router={router} />);
  await screen.findByTestId('graph-canvas');
  const button = await screen.findByRole('button', { name: /지도에서 보기/ });
  return { router, graph, edge, button };
}

const MISSING_TARGET = '이 답변의 대상이 해당 버전의 지도에 없어요.';

describe('D-AI-02b · saved-answer relation navigation', () => {
  it('keeps the answer open when its edge is missing from the current snapshot', async () => {
    const { router, button } = await setup({ id: 'edge-not-on-this-map' });
    const before = router.state.location.search;
    await userEvent.click(button);
    expect(
      await screen.findByText(/지금 지도에서 그대로 열 수 없어요/),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: /지도에서 보기/ })).toBe(button);
    expect(router.state.location.search).toBe(before);
  });

  it.each([true, false])(
    'waits for another snapshot and reports whether its edge exists (available: %s)',
    async (available) => {
      const { router, graph, edge, button } = await setup({
        graphVersion: 'another-version',
      });
      const next = deferred<GraphResponse>();
      vi.mocked(getGraph).mockReturnValueOnce(next.promise);
      vi.spyOn(relationApi, 'getRelation').mockImplementation(async (id) => {
        const relation = createMockRelation(id);
        return {
          ...relation,
          metadata: { ...relation.metadata, graphVersion: 'another-version' },
        };
      });
      await userEvent.click(button);
      expect(
        screen.queryByRole('button', { name: /지도에서 보기/ }),
      ).toBeNull();
      expect(screen.queryByTestId('graph-canvas')).toBeNull();
      expect(screen.queryByText(MISSING_TARGET)).toBeNull();
      expect(
        new URLSearchParams(router.state.location.search).get('graphVersion'),
      ).toBe('another-version');

      await act(async () => {
        next.resolve({
          ...graph,
          edges: available
            ? graph.edges
            : graph.edges.filter((item) => item.id !== edge.id),
          metadata: { ...graph.metadata, graphVersion: 'another-version' },
        });
      });
      await screen.findByTestId('graph-canvas');
      if (available) {
        const details = await screen.findByRole('region', {
          name: '관계 정보',
        });
        expect(
          within(details).getByText('HBM3E 12단 경쟁 → HBM4 공급 계약'),
        ).toBeTruthy();
        expect(
          new URLSearchParams(router.state.location.search).get('select'),
        ).toBe(`edge:${edge.id}`);
        expect(screen.queryByText(MISSING_TARGET)).toBeNull();
      } else {
        expect(await screen.findByText(MISSING_TARGET)).toBeTruthy();
      }
    },
  );
});
