import {
  configure,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AiChatDrawer from '@/components/ai/AiChatDrawer';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { useAuthStore } from '@/stores/useAuthStore';
import type {
  ChatConversationList,
  ChatConversationSummary,
  ChatJob,
} from '@/types/ai';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  json,
  noContent,
  type FakeServer,
} from '../support/fakeServer';

// D-AI-02 대화 기록(와이어프레임 없음, 임시 설계): 지난 대화 열기와, 서버가 연 경우의 대화 삭제.

const CURRENT = '/api/v1/chat/sessions/current';
const LIST = '/api/v1/chat/sessions';
const SESSION = '/api/v1/chat/sessions/:id';

const member: Session = {
  authenticated: true,
  kind: 'member',
  user: { id: 'mem-1', email: 'mem-1@zoop.test', displayName: '회원' },
  setup: { completed: true, tutorialCompleted: true },
  csrfToken: 'csrf-member',
  expiresAt: null,
};

function job(id: string, sessionId: string, question: string): ChatJob {
  return {
    id,
    sessionId,
    seq: 1,
    question,
    status: 'cancelled',
    phase: null,
    outcome: null,
    askedAt: '2026-10-27T00:00:00Z',
    context: {
      items: [],
      evidenceCount: 0,
      period: null,
      asOf: null,
      graphVersion: 'gv-1',
    },
    resolves: null,
    failure: null,
    result: null,
    runs: 0,
    createdAt: '2026-10-27T00:00:00Z',
    updatedAt: '2026-10-27T00:00:00Z',
    finishedAt: '2026-10-27T00:00:01Z',
  };
}

function conversation(sessionId: string, question: string) {
  return {
    session: { id: sessionId, createdAt: '2026-10-27T00:00:00Z', jobs: 1 },
    jobs: [job(`job-${sessionId}`, sessionId, question)],
  };
}

function summary(id: string, title: string): ChatConversationSummary {
  return {
    id,
    title,
    createdAt: '2026-10-27T00:00:00Z',
    updatedAt: '2026-10-27T05:30:00Z',
    jobs: 1,
  };
}

function page(
  items: ChatConversationSummary[],
  patch: Partial<ChatConversationList> = {},
): ChatConversationList {
  return { items, nextCursor: null, deleteEnabled: false, ...patch };
}

let server: FakeServer;

configure({ asyncUtilTimeout: 3000 });

beforeEach(() => {
  server = createFakeServer();
  useAuthStore.getState().setSession(member);
  useAiChatStore.getState().reset();
  server.on('GET', CURRENT, () =>
    json({ conversation: conversation('conv-now', '지금 질문') }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  useAuthStore.getState().clearSession();
});

async function openHistory() {
  useAiChatStore.getState().open(null);
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <AiChatDrawer />
    </MemoryRouter>,
  );
  await screen.findByText('지금 질문');
  await user.click(screen.getByRole('button', { name: '대화 기록' }));
  return user;
}

describe('D-AI-02 · conversation history', () => {
  it('lists past conversations, marks the current one and opens another without asking the model', async () => {
    server.on('GET', LIST, () =>
      json(
        page([
          summary('conv-now', '지금 질문'),
          summary('conv-old', '지난 질문'),
        ]),
      ),
    );
    server.on('GET', SESSION, (request) =>
      json(conversation(request.params.id, '지난 질문')),
    );
    // ':id' also matches 'current': the latest conversation is answered after it.
    server.on('GET', CURRENT, () =>
      json({ conversation: conversation('conv-now', '지금 질문') }),
    );

    const user = await openHistory();
    const list = await screen.findByRole('list', { name: '지난 대화' });
    const current = within(list).getByRole('button', { name: /지금 질문/ });
    expect(current.getAttribute('aria-current')).toBe('true');
    expect(current.textContent).toContain('2026-10-27 14:30 KST');
    expect(screen.queryByRole('button', { name: /대화 삭제/ })).toBeNull();
    expect(
      screen.getByText('대화 기록은 회원 탈퇴 시 모두 삭제돼요.'),
    ).toBeTruthy();

    await user.click(within(list).getByRole('button', { name: /지난 질문/ }));
    await screen.findByLabelText('질문');
    expect(await screen.findByText('지난 질문')).toBeTruthy();
    expect(screen.queryByText('지금 질문')).toBeNull();
    expect(
      server
        .calls('GET', SESSION)
        .map((call) => call.path)
        .filter((path) => path !== CURRENT),
    ).toEqual(['/api/v1/chat/sessions/conv-old']);
    expect(server.calls('POST', '/api/v1/chat/sessions/:id/jobs')).toEqual([]);
  });

  it('continues with the next cursor and says when there is nothing yet', async () => {
    server.on('GET', LIST, (request) =>
      json(
        request.query.get('cursor') === 'next-1'
          ? page([summary('conv-2', '두 번째 쪽')])
          : page([summary('conv-1', '첫 쪽')], { nextCursor: 'next-1' }),
      ),
    );
    const user = await openHistory();
    await screen.findByText('첫 쪽');
    await user.click(screen.getByRole('button', { name: '더 보기' }));
    await screen.findByText('두 번째 쪽');
    expect(screen.getByText('첫 쪽')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '더 보기' })).toBeNull();
  });

  it('shows the empty and the failed list apart and retries only the read', async () => {
    let fail = true;
    server.on('GET', LIST, () =>
      fail ? apiError(503, 'SOURCE_UNAVAILABLE') : json(page([])),
    );
    const user = await openHistory();
    await screen.findByText('대화 기록을 불러오지 못했어요.');
    fail = false;
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText(/아직 질문한 대화가 없어요/);
  });

  it('deletes only after a confirmation when the server allows it, and the deleted current conversation leaves the chat empty', async () => {
    let items = [
      summary('conv-now', '지금 질문'),
      summary('conv-old', '지난 질문'),
    ];
    server.on('GET', LIST, () => json(page(items, { deleteEnabled: true })));
    server.on('DELETE', SESSION, (request) => {
      items = items.filter((item) => item.id !== request.params.id);
      return noContent();
    });

    const user = await openHistory();
    await user.click(
      await screen.findByRole('button', { name: '“지금 질문” 대화 삭제' }),
    );
    const confirm = screen.getByRole('group', { name: '대화 삭제 확인' });
    expect(server.calls('DELETE', SESSION)).toEqual([]);
    await user.click(within(confirm).getByRole('button', { name: '삭제' }));

    await screen.findByText('대화를 삭제했어요.');
    const [call] = server.calls('DELETE', SESSION);
    expect(call.path).toBe('/api/v1/chat/sessions/conv-now');
    expect(call.headers.get('X-CSRF-Token')).toBe('csrf-member');
    await waitFor(() => expect(screen.queryByText('지금 질문')).toBeNull());
    expect(screen.getByText('지난 질문')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '← 대화로 돌아가기' }));
    await screen.findByText(/궁금한 점을 입력해 보세요/);
  });

  it('keeps a conversation with a question in progress and says why', async () => {
    server.on('GET', LIST, () =>
      json(page([summary('conv-now', '지금 질문')], { deleteEnabled: true })),
    );
    server.on('DELETE', SESSION, () => apiError(409, 'JOB_IN_PROGRESS'));
    const user = await openHistory();
    await user.click(
      await screen.findByRole('button', { name: '“지금 질문” 대화 삭제' }),
    );
    await user.click(
      within(screen.getByRole('group', { name: '대화 삭제 확인' })).getByRole(
        'button',
        { name: '삭제' },
      ),
    );
    await screen.findByText(/처리 중인 질문이 있어 삭제할 수 없어요/);
    await user.click(screen.getByRole('button', { name: '← 대화로 돌아가기' }));
    expect(await screen.findByText('지금 질문')).toBeTruthy();
  });
});
