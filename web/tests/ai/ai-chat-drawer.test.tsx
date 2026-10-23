import {
  act,
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
import { contextFromTarget } from '@/hooks/use-chat-conversation';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { useAuthStore } from '@/stores/useAuthStore';
import type { ChatJob, ChatResult } from '@/types/ai';
import type { Session } from '@/types/auth';
import type { GraphTarget } from '@/types/map';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';

// D-AI-01 · D-AI-01b · D-AI-02 · D-AI-02b — docs/wireframe/ai-chatbot-state-contract.md

const CURRENT = '/api/v1/chat/sessions/current';
const SESSION = '/api/v1/chat/sessions/:id';
const JOBS = '/api/v1/chat/sessions/:id/jobs';
const JOB = '/api/v1/chat/jobs/:id';
const RETRY = '/api/v1/chat/jobs/:id/retry';
const CANCEL = '/api/v1/chat/jobs/:id/cancel';

function member(id: string): Session {
  return {
    authenticated: true,
    kind: 'member',
    user: { id, email: `${id}@zoop.test`, displayName: '회원' },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: 'csrf-member',
    expiresAt: null,
  };
}

const SAMSUNG: GraphTarget = {
  kind: 'company',
  id: 'KRX:005930',
  label: '삼성전자',
  mapContext: {
    url: '/?mode=all',
    graphVersion: 'gv-1',
    asOf: '2026-10-21T00:00:00Z',
  },
};

function result(patch: Partial<ChatResult> = {}): ChatResult {
  return {
    outcome: 'answered',
    messageId: 'msg-1',
    answer: '',
    sections: [],
    answerBasis: 'none',
    reason: null,
    sources: [],
    citations: [],
    graphTargets: [],
    applied: {
      companies: [],
      issues: [],
      period: null,
      graphVersion: 'gv-1',
      dataAsOf: '2026-10-21T00:00:00Z',
      questionOverrodeContext: false,
    },
    choices: [],
    action: null,
    limitations: [],
    ...patch,
  };
}

function job(patch: Partial<ChatJob> = {}): ChatJob {
  return {
    id: 'job-00000001',
    sessionId: 'conv-0001',
    seq: 1,
    question: 'HBM이 뭐야?',
    status: 'completed',
    phase: null,
    outcome: 'answered',
    askedAt: '2026-10-21T00:00:00Z',
    context: {
      items: [],
      evidenceCount: 0,
      period: null,
      asOf: null,
      graphVersion: 'gv-1',
    },
    resolves: null,
    failure: null,
    result: result({
      sections: [
        {
          basis: 'general_knowledge',
          text: '일반 개념 설명입니다. 최신 기업·시장 사실은 별도 조회가 필요합니다. HBM은 메모리입니다.',
          evidenceIds: [],
        },
      ],
      answerBasis: 'general_knowledge',
    }),
    runs: 1,
    createdAt: '2026-10-21T00:00:00Z',
    updatedAt: '2026-10-21T00:00:00Z',
    finishedAt: '2026-10-21T00:00:01Z',
    ...patch,
  };
}

function conversation(jobs: ChatJob[], id = 'conv-0001') {
  return {
    conversation: {
      session: { id, createdAt: '2026-10-21T00:00:00Z', jobs: jobs.length },
      jobs,
    },
  };
}

let server: FakeServer;

// Each step waits on a fake HTTP round trip and a React update; CI runners under load need more than the default 1 s.
configure({ asyncUtilTimeout: 3000 });

beforeEach(() => {
  server = createFakeServer();
  useAuthStore.getState().setSession(member('mem-1'));
  useAiChatStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  useAuthStore.getState().clearSession();
});

function open(target: GraphTarget | null = SAMSUNG, onViewOnMap = vi.fn()) {
  useAiChatStore.getState().open(target);
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <AiChatDrawer onViewOnMap={onViewOnMap} />
    </MemoryRouter>,
  );
  return { user, onViewOnMap };
}

describe('D-AI-01 · asking with a linked target', () => {
  it('sends one job with the selected context and the jobId as Idempotency-Key, then polls it to its result', async () => {
    server.on('GET', CURRENT, () => json({ conversation: null }));
    server.on('PUT', SESSION, (request) =>
      json(
        { id: request.params.id, createdAt: '2026-10-21T00:00:00Z', jobs: 0 },
        201,
      ),
    );
    let submitted: ChatJob | null = null;
    server.on('POST', JOBS, (request) => {
      const body = request.body as { jobId: string; question: string };
      submitted = job({
        id: body.jobId,
        sessionId: request.params.id,
        question: body.question,
        status: 'running',
        phase: 'retrieving',
        outcome: null,
        result: null,
        finishedAt: null,
      });
      return json(submitted, 202);
    });
    server.on('GET', JOB, () =>
      json({
        ...submitted!,
        status: 'completed',
        phase: null,
        outcome: 'answered',
        result: job().result,
      }),
    );

    const { user } = open();
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    expect(screen.getByText('질문 대상: 삼성전자')).toBeTruthy();
    await user.type(screen.getByLabelText('질문'), '삼성전자 최근 이슈는?');
    await user.keyboard('{Enter}');

    const card = await screen.findByRole('article', {
      name: '삼성전자 최근 이슈는?',
    });
    expect(within(card).getByText('자료 확인')).toBeTruthy();
    expect(
      screen.getByRole('button', { name: '보내기' }).hasAttribute('disabled'),
    ).toBe(true);

    const [post] = server.calls('POST', JOBS);
    const body = post.body as {
      jobId: string;
      context: unknown;
      resolves?: unknown;
    };
    expect(post.headers.get('Idempotency-Key')).toBe(body.jobId);
    expect(body.context).toEqual({
      contextIds: ['KRX:005930'],
      graphVersion: 'gv-1',
    });
    expect(body.resolves).toBeUndefined();
    expect(server.calls('PUT', SESSION)[0].params.id).toBe(post.params.id);
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe(
      '',
    );

    await within(card).findByText(/HBM은 메모리입니다/, {}, { timeout: 3000 });
    expect(within(card).getAllByText('일반 개념').length).toBeGreaterThan(0);
    expect(server.calls('POST', JOBS)).toHaveLength(1);
  });

  it('sends no context when the target is unlinked and refuses a blank question', async () => {
    server.on('GET', CURRENT, () => json(conversation([])));
    server.on('POST', JOBS, (request) =>
      json(job({ id: (request.body as { jobId: string }).jobId })),
    );
    const { user } = open();
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    await user.click(screen.getByRole('checkbox'));
    expect(screen.getByText('질문 대상: 없음')).toBeTruthy();
    expect(screen.getByText(/연결한 대상이 없어요/)).toBeTruthy();

    await user.type(screen.getByLabelText('질문'), '   ');
    expect(
      screen.getByRole('button', { name: '보내기' }).hasAttribute('disabled'),
    ).toBe(true);
    await user.clear(screen.getByLabelText('질문'));
    await user.type(
      screen.getByLabelText('질문'),
      'HBM이 뭐야?{Shift>}{Enter}{/Shift}설명해줘',
    );
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe(
      'HBM이 뭐야?\n설명해줘',
    );
    await user.click(screen.getByRole('button', { name: '보내기' }));
    await waitFor(() => expect(server.calls('POST', JOBS)).toHaveLength(1));
    expect(
      (server.calls('POST', JOBS)[0].body as { context?: unknown }).context,
    ).toBeUndefined();
    expect(server.calls('PUT', SESSION)).toHaveLength(0);
  });

  it('resends an unanswered question with the same jobId and creates one job', async () => {
    server.on('GET', CURRENT, () => json(conversation([])));
    let attempts = 0;
    server.on('POST', JOBS, (request) => {
      attempts += 1;
      if (attempts === 1)
        return apiError(
          503,
          'MODEL_UNAVAILABLE',
          '답변 기능을 일시적으로 사용할 수 없습니다.',
        );
      return json(
        job({
          id: (request.body as { jobId: string }).jobId,
          question: 'HBM?',
        }),
        202,
      );
    });
    const { user } = open(null);
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    await user.type(screen.getByLabelText('질문'), 'HBM?');
    await user.click(screen.getByRole('button', { name: '보내기' }));
    expect((await screen.findByRole('alert')).textContent).toContain(
      '답변 기능을 일시적으로 사용할 수 없습니다.',
    );
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe(
      'HBM?',
    );

    await user.click(
      screen.getByRole('button', { name: '같은 질문 다시 보내기' }),
    );
    await screen.findByRole('article', { name: 'HBM?' });
    const [first, second] = server.calls('POST', JOBS);
    expect((second.body as { jobId: string }).jobId).toBe(
      (first.body as { jobId: string }).jobId,
    );
    expect((screen.getByLabelText('질문') as HTMLTextAreaElement).value).toBe(
      '',
    );
  });

  it('does not call a question that is still being sent unconfirmed', async () => {
    server.on('GET', CURRENT, () => json(conversation([])));
    const accepted = deferred<Response>();
    let sentId = '';
    server.on('POST', JOBS, (request) => {
      sentId = (request.body as { jobId: string }).jobId;
      return accepted.promise;
    });
    const { user } = open(null);
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    await user.type(screen.getByLabelText('질문'), 'HBM?');
    await user.click(screen.getByRole('button', { name: '보내기' }));
    await waitFor(() => expect(server.calls('POST', JOBS)).toHaveLength(1));
    expect(screen.queryByText(/접수됐는지 확인하지 못했어요/)).toBeNull();
    accepted.resolve(json(job({ id: sentId, question: 'HBM?' }), 202));
    await screen.findByRole('article', { name: 'HBM?' });
  });

  it('keeps an accepted status whose body could not be read as unconfirmed, never as refused', async () => {
    server.on('GET', CURRENT, () => json(conversation([])));
    server.on(
      'POST',
      JOBS,
      () =>
        new Response('{"broken', {
          status: 202,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    const { user } = open(null);
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    await user.type(screen.getByLabelText('질문'), 'HBM?');
    await user.click(screen.getByRole('button', { name: '보내기' }));
    await screen.findByText(/질문이 접수됐는지 확인하지 못했어요/);
    expect(
      screen.getByRole('button', { name: '같은 질문 다시 보내기' }),
    ).toBeTruthy();
  });

  it('keeps an unconfirmed question pending: no new id until it is resent or discarded', async () => {
    // SESSION also matches /current, so CURRENT is registered last to win that path.
    server.on('GET', SESSION, () => json(conversation([]).conversation));
    server.on('GET', CURRENT, () => json(conversation([])));
    server.on('POST', JOBS, () => {
      throw new Error('connection reset');
    });
    const { user } = open(null);
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    await user.type(screen.getByLabelText('질문'), '첫 질문');
    await user.click(screen.getByRole('button', { name: '보내기' }));
    await screen.findByText(/질문이 접수됐는지 확인하지 못했어요/);

    // A different question cannot be sent while the first one may exist on the server.
    await user.clear(screen.getByLabelText('질문'));
    await user.type(screen.getByLabelText('질문'), '두 번째 질문');
    expect(
      screen.getByRole('button', { name: '보내기' }).hasAttribute('disabled'),
    ).toBe(true);
    expect(server.calls('POST', JOBS)).toHaveLength(1);
    // Nor can a new conversation start: the unconfirmed question is resent or discarded first.
    expect(
      screen.getByRole('button', { name: '새 대화' }).hasAttribute('disabled'),
    ).toBe(true);

    await user.click(
      screen.getByRole('button', { name: '보내지 않은 것으로 하기' }),
    );
    // Discarding re-reads the conversation so a question the server did accept would appear.
    await waitFor(() =>
      expect(
        server
          .calls('GET', SESSION)
          .filter((call) => call.params.id === 'conv-0001'),
      ).toHaveLength(1),
    );
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '보내기' }).hasAttribute('disabled'),
      ).toBe(false),
    );
  });

  it('retries a conversation that could not be created with the same id before sending', async () => {
    server.on('GET', CURRENT, () => json({ conversation: null }));
    let puts = 0;
    server.on('PUT', SESSION, (request) => {
      puts += 1;
      if (puts === 1) return apiError(503, 'SOURCE_UNAVAILABLE');
      return json({
        id: request.params.id,
        createdAt: '2026-10-21T00:00:00Z',
        jobs: 0,
      });
    });
    server.on('POST', JOBS, (request) =>
      json(
        job({
          id: (request.body as { jobId: string }).jobId,
          sessionId: request.params.id,
          question: '질문',
        }),
        202,
      ),
    );
    const { user } = open(null);
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    await user.type(screen.getByLabelText('질문'), '질문');
    await user.click(screen.getByRole('button', { name: '보내기' }));
    await user.click(
      await screen.findByRole('button', { name: '같은 질문 다시 보내기' }),
    );
    await screen.findByRole('article', { name: '질문' });
    const [first, second] = server.calls('PUT', SESSION);
    expect(second.params.id).toBe(first.params.id);
    expect(server.calls('POST', JOBS)[0].params.id).toBe(first.params.id);
  });

  it('a new conversation drops a restore that arrives late', async () => {
    const late = deferred<Response>();
    server.on('GET', CURRENT, () => late.promise);
    server.on('PUT', SESSION, (request) =>
      json(
        { id: request.params.id, createdAt: '2026-10-21T00:00:00Z', jobs: 0 },
        201,
      ),
    );
    const { user } = open(null);
    await waitFor(() => expect(server.calls('GET', CURRENT)).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: '새 대화' }));
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    late.resolve(json(conversation([job({ question: '이전 대화의 질문' })])));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText('이전 대화의 질문')).toBeNull();
  });

  it('shows the active job of a busy conversation instead of creating another', async () => {
    const running = job({
      id: 'job-running1',
      question: '처리 중인 질문',
      status: 'running',
      phase: 'planning',
      outcome: null,
      result: null,
    });
    let reads = 0;
    server.on('GET', CURRENT, () => json(conversation([])));
    server.on('GET', SESSION, () => {
      reads += 1;
      return json(conversation([running]).conversation);
    });
    server.on('POST', JOBS, () =>
      apiError(
        409,
        'JOB_IN_PROGRESS',
        '이 대화에서 아직 처리 중인 질문이 있습니다.',
      ),
    );
    server.on('GET', JOB, () => json(running));
    // An earlier conversation is known: the restore after 409 reads that one.
    server.on('GET', CURRENT, () =>
      json(conversation([job({ id: 'job-done0001', question: '이전 질문' })])),
    );
    const { user } = open(null);
    await screen.findByRole('article', { name: '이전 질문' });
    await user.type(screen.getByLabelText('질문'), '새 질문');
    await user.click(screen.getByRole('button', { name: '보내기' }));
    await screen.findByRole('article', { name: '처리 중인 질문' });
    expect(reads).toBe(1);
    expect(screen.getByText(/아직 처리 중인 질문이 있어요/)).toBeTruthy();
  });
});

describe('D-AI-01b · clarification', () => {
  const clarification = job({
    id: 'job-clarify1',
    question: '그 기업은 언제?',
    outcome: 'clarification',
    result: result({
      outcome: 'clarification',
      reason: '어느 기업인지 골라 주세요.',
      choices: [
        { id: 'c-opaque-1', label: '삼성전자', kind: 'company' },
        { id: 'c-opaque-2', label: 'SK하이닉스', kind: 'company' },
      ],
    }),
  });

  it('answers with a choice as a new job that resolves the original, without context', async () => {
    server.on('GET', CURRENT, () => json(conversation([clarification])));
    server.on('POST', JOBS, (request) => {
      const body = request.body as {
        jobId: string;
        question: string;
        resolves: ChatJob['resolves'];
      };
      return json(
        job({
          id: body.jobId,
          seq: 2,
          question: body.question,
          resolves: body.resolves,
        }),
        202,
      );
    });
    const { user } = open();
    await screen.findByText('어느 기업인지 골라 주세요.');
    await user.click(screen.getByRole('button', { name: 'SK하이닉스' }));
    await screen.findByText('확인 질문 “그 기업은 언제?”에 대한 답');
    const body = server.calls('POST', JOBS)[0].body as Record<string, unknown>;
    expect(body.question).toBe('SK하이닉스');
    expect(body.resolves).toEqual({
      jobId: 'job-clarify1',
      choiceId: 'c-opaque-2',
    });
    expect(body.context).toBeUndefined();
    // The original clarification stays and its choices can be picked again.
    expect(screen.getByRole('button', { name: '삼성전자' })).toBeTruthy();
  });

  it('answers in free text with choiceId null', async () => {
    server.on('GET', CURRENT, () => json(conversation([clarification])));
    server.on('POST', JOBS, (request) =>
      json(job({ id: (request.body as { jobId: string }).jobId, seq: 2 }), 202),
    );
    const { user } = open();
    await user.click(
      await screen.findByRole('button', { name: '직접 입력해 답하기' }),
    );
    expect(screen.getByText(/에 답하는 중/)).toBeTruthy();
    await user.type(screen.getByLabelText('질문'), 'LG에너지솔루션');
    await user.click(screen.getByRole('button', { name: '보내기' }));
    await waitFor(() => expect(server.calls('POST', JOBS)).toHaveLength(1));
    expect(
      (server.calls('POST', JOBS)[0].body as Record<string, unknown>).resolves,
    ).toEqual({
      jobId: 'job-clarify1',
      choiceId: null,
    });
  });
});

describe('D-AI-02 · job states and stored results', () => {
  it('renders a mixed answer by its sections, limitations, citations, map targets and applied scope', async () => {
    const answered = job({
      question: 'HBM이 뭐고 SK하이닉스 최근 HBM 뉴스는?',
      result: result({
        answer: 'x',
        answerBasis: 'mixed',
        sections: [
          {
            basis: 'general_knowledge',
            text: '일반 개념 설명입니다. HBM은 메모리입니다.',
            evidenceIds: [],
          },
          {
            basis: 'evidence_grounded',
            text: 'SK하이닉스는 HBM을 공급합니다.',
            evidenceIds: ['ev-1'],
          },
        ],
        citations: [
          {
            sourceKind: 'article',
            evidenceId: 'ev-1',
            quote: 'HBM 공급 계약',
            articleId: 'art-1',
            articleVersion: 'v1',
            docId: null,
            docVersion: null,
            start: 0,
            end: 8,
            articleTitle: 'HBM 공급 보도',
            publisher: '언론사',
            publishedAt: '2026-10-20T00:00:00Z',
            url: 'https://example.com/a',
          },
        ],
        sources: ['art-1'],
        graphTargets: [{ id: 'KRX:000660', kind: 'company' }],
        limitations: [
          {
            kind: 'investment_advice',
            label: '지금 살 주식',
            message: '매수·매도 같은 투자 판단은 제공하지 않아요.',
          },
        ],
        applied: {
          companies: [{ id: 'KRX:000660', label: 'SK하이닉스' }],
          issues: [],
          period: null,
          graphVersion: 'gv-1',
          dataAsOf: '2026-10-21T00:00:00Z',
          questionOverrodeContext: true,
        },
      }),
    });
    server.on('GET', CURRENT, () => json(conversation([answered])));
    const { user, onViewOnMap } = open();
    const card = await screen.findByRole('article', {
      name: 'HBM이 뭐고 SK하이닉스 최근 HBM 뉴스는?',
    });
    expect(within(card).getByText('일반 개념 + 근거 확인됨')).toBeTruthy();
    expect(
      within(card).getByRole('region', { name: '일반 개념 구간' }),
    ).toBeTruthy();
    expect(
      within(card).getByRole('region', { name: '근거 확인됨 구간' })
        .textContent,
    ).toContain('근거 [1]');
    const limits = within(card).getByRole('region', {
      name: '답하지 않은 부분',
    });
    expect(limits.textContent).toContain('지금 살 주식');
    expect(limits.textContent).toContain('투자 판단은 제공하지 않아요');
    expect(within(card).getByText('HBM 공급 계약')).toBeTruthy();
    expect(
      within(card)
        .getByRole('link', { name: /원문 보기/ })
        .getAttribute('href'),
    ).toBe('https://example.com/a');
    expect(within(card).getByText(/질문에 적힌 대상을 기준으로/)).toBeTruthy();
    onViewOnMap.mockReturnValueOnce(true);
    await user.click(
      within(card).getByRole('button', { name: /지도에서 보기 · SK하이닉스/ }),
    );
    // Only the cutoff the question named: a version-pinned answer gets no time filter from its data time.
    expect(onViewOnMap).toHaveBeenCalledWith({
      id: 'KRX:000660',
      kind: 'company',
      graphVersion: 'gv-1',
      asOf: null,
    });
    expect(within(card).queryByText(/그대로 열 수 없어요/)).toBeNull();
    onViewOnMap.mockReturnValueOnce(false);
    await user.click(
      within(card).getByRole('button', { name: /지도에서 보기 · SK하이닉스/ }),
    );
    expect(
      within(card).getByText(/그래프 버전 gv-1 기준이라 지금 지도에서/),
    ).toBeTruthy();
  });

  it('shows a withheld answer as the server sent it, without a basis badge', async () => {
    const withheld = job({
      result: result({
        answer: '이 답변이 인용한 자료를 지금은 보여드릴 수 없어요.',
        sections: [],
        answerBasis: 'none',
      }),
    });
    server.on('GET', CURRENT, () => json(conversation([withheld])));
    open();
    const card = await screen.findByRole('article', { name: 'HBM이 뭐야?' });
    expect(
      within(card).getByText(
        '이 답변이 인용한 자료를 지금은 보여드릴 수 없어요.',
      ),
    ).toBeTruthy();
    expect(within(card).queryByText('근거 확인됨')).toBeNull();
    expect(within(card).queryByText('일반 개념')).toBeNull();
  });

  it('offers only the retry the failure allows and sends it with an Idempotency-Key', async () => {
    const rerun = job({
      id: 'job-failed01',
      question: '실패한 질문',
      status: 'failed',
      outcome: null,
      result: null,
      failure: {
        kind: 'transient',
        reason: 'tool_timeout',
        message: '자료 조회가 제한 시간 안에 끝나지 않았어요.',
        retry: 'rerun',
      },
    });
    const unknown = job({
      id: 'job-unknown1',
      seq: 2,
      question: '응답 불명 질문',
      status: 'failed',
      outcome: null,
      result: null,
      failure: {
        kind: 'transient',
        reason: 'response_unknown',
        message: '처리 결과를 확인하지 못했어요.',
        retry: null,
      },
    });
    server.on('GET', CURRENT, () => json(conversation([rerun, unknown])));
    server.on('POST', RETRY, () =>
      json({ ...rerun, status: 'queued', failure: null }, 202),
    );
    server.on('GET', JOB, () =>
      json({ ...rerun, status: 'queued', failure: null }),
    );
    const { user } = open();
    const failed = await screen.findByRole('article', { name: '실패한 질문' });
    const lost = screen.getByRole('article', { name: '응답 불명 질문' });
    expect(within(lost).queryByRole('button', { name: /다시/ })).toBeNull();
    expect(within(lost).getByText(/작업 ID job-unknown1/)).toBeTruthy();

    await user.click(
      within(failed).getByRole('button', { name: '질문 다시 처리' }),
    );
    await within(failed).findByText('질문을 접수했어요.');
    expect(
      server.calls('POST', RETRY)[0].headers.get('Idempotency-Key'),
    ).toBeTruthy();
  });

  it('announces the running phase in the live region', async () => {
    const running = job({
      status: 'running',
      phase: 'writing',
      outcome: null,
      result: null,
      finishedAt: null,
    });
    server.on('GET', CURRENT, () => json(conversation([running])));
    server.on('GET', JOB, () => json(running));
    open();
    await screen.findByRole('article', { name: 'HBM이 뭐야?' });
    const live = document.querySelector('[aria-live="polite"]');
    expect(live?.textContent).toContain('답변 작성');
  });

  it('a new conversation waits for a retry in flight, then starts clean', async () => {
    const failed = job({
      id: 'job-failed02',
      question: '이전 대화의 실패',
      status: 'failed',
      outcome: null,
      result: null,
      failure: {
        kind: 'transient',
        reason: 'tool_timeout',
        message: '자료 조회가 제한 시간 안에 끝나지 않았어요.',
        retry: 'rerun',
      },
    });
    const retried = deferred<Response>();
    server.on('GET', CURRENT, () => json(conversation([failed])));
    server.on('POST', RETRY, () => retried.promise);
    server.on('PUT', SESSION, (request) =>
      json(
        { id: request.params.id, createdAt: '2026-10-21T00:00:00Z', jobs: 0 },
        201,
      ),
    );
    const { user } = open();
    const card = await screen.findByRole('article', {
      name: '이전 대화의 실패',
    });
    await user.click(
      within(card).getByRole('button', { name: '질문 다시 처리' }),
    );
    // The retry may be accepted: switching now would drop its answer, so the switch waits.
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: '새 대화' })
          .hasAttribute('disabled'),
      ).toBe(true),
    );
    expect(server.calls('PUT', SESSION)).toHaveLength(0);
    retried.resolve(
      json({ ...failed, status: 'queued', failure: null, phase: null }, 202),
    );
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: '새 대화' })
          .hasAttribute('disabled'),
      ).toBe(false),
    );
    await user.click(screen.getByRole('button', { name: '새 대화' }));
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    expect(screen.queryByText('이전 대화의 실패')).toBeNull();
  });

  it('cancels a queued job', async () => {
    const queued = job({
      status: 'queued',
      outcome: null,
      result: null,
      finishedAt: null,
    });
    server.on('GET', CURRENT, () => json(conversation([queued])));
    server.on('GET', JOB, () => json(queued));
    server.on('POST', CANCEL, () => json({ ...queued, status: 'cancelled' }));
    const { user } = open();
    await user.click(await screen.findByRole('button', { name: '질문 취소' }));
    await screen.findByText(/취소한 질문이에요/);
    expect(
      server.calls('POST', CANCEL)[0].headers.get('Idempotency-Key'),
    ).toBeTruthy();
  });

  it('stops polling on a failed status read and resumes only when asked', async () => {
    const running = job({
      status: 'running',
      phase: 'writing',
      outcome: null,
      result: null,
      finishedAt: null,
    });
    server.on('GET', CURRENT, () => json(conversation([running])));
    server.on('GET', JOB, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = open();
    await screen.findByText(
      /질문 상태를 확인하지 못했어요/,
      {},
      { timeout: 3000 },
    );
    const reads = server.calls('GET', JOB).length;
    server.on('GET', JOB, () =>
      json({
        ...running,
        status: 'completed',
        phase: null,
        outcome: 'answered',
        result: job().result,
      }),
    );
    await user.click(screen.getByRole('button', { name: '다시 확인' }));
    await screen.findByText(/HBM은 메모리입니다/, {}, { timeout: 3000 });
    expect(server.calls('GET', JOB).length).toBe(reads + 1);
    expect(server.calls('POST', JOBS)).toHaveLength(0);
  });
});

describe('D-AI-02b · conversation read failure', () => {
  it('shows the error with its code and request id, rechecks by reading only and keeps sending off', async () => {
    let fail = true;
    server.on('GET', CURRENT, () =>
      fail
        ? json(
            {
              error: {
                code: 'SOURCE_UNAVAILABLE',
                message: 'x',
                requestId: 'req-42',
                retryable: true,
              },
            },
            503,
          )
        : json(conversation([job({ question: '회수된 질문' })])),
    );
    const { user } = open();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('대화를 불러오지 못했어요.');
    expect(alert.textContent).toContain('SOURCE_UNAVAILABLE');
    expect(alert.textContent).toContain('req-42');
    await user.type(screen.getByLabelText('질문'), '질문');
    expect(
      screen.getByRole('button', { name: '보내기' }).hasAttribute('disabled'),
    ).toBe(true);

    fail = false;
    await user.click(within(alert).getByRole('button', { name: '다시 확인' }));
    await screen.findByRole('article', { name: '회수된 질문' });
    expect(server.calls('GET', CURRENT)).toHaveLength(2);
    expect(server.calls('POST', JOBS)).toHaveLength(0);
  });
});

describe('membership', () => {
  it('asks a guest to log in and sends nothing', async () => {
    useAuthStore.getState().clearSession();
    open();
    expect(
      await screen.findByRole('link', { name: '로그인 후 질문하기' }),
    ).toBeTruthy();
    expect(server.requests).toHaveLength(0);
  });

  it('drops a late conversation of the previous member', async () => {
    const late = deferred<Response>();
    server.on('GET', CURRENT, () => late.promise);
    open();
    await waitFor(() => expect(server.calls('GET', CURRENT)).toHaveLength(1));
    server.on('GET', CURRENT, () => json(conversation([])));
    act(() => {
      useAuthStore.getState().setSession(member('mem-2'));
      useAiChatStore.getState().open(null);
    });
    await screen.findByText(/궁금한 점을 입력해 보세요/);
    late.resolve(json(conversation([job({ question: '이전 회원의 질문' })])));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText('이전 회원의 질문')).toBeNull();
  });
});

describe('contextFromTarget', () => {
  it('keeps the cutoff the member set on the map address', () => {
    expect(
      contextFromTarget({
        kind: 'company',
        id: 'KRX:005930',
        mapContext: {
          url: '/?mode=all&companyId=KRX%3A005930&asOf=2026-10-01T00%3A00%3A00Z&graphVersion=gv-old',
          graphVersion: 'gv-old',
          asOf: '2026-10-01T00:00:00Z',
        },
      }),
    ).toEqual({
      contextIds: ['KRX:005930'],
      graphVersion: 'gv-old',
      asOf: '2026-10-01T00:00:00Z',
    });
  });

  it('sends only a cutoff the map itself applies: a company map with an exact time', () => {
    for (const url of [
      '/?mode=all&asOf=2026-10-01T00%3A00%3A00Z', // no company map: the map ignores asOf
      '/?companyId=KRX%3A005930&asOf=2026-10-01', // not an exact time with a zone
    ]) {
      expect(
        contextFromTarget({
          kind: 'company',
          id: 'KRX:005930',
          mapContext: { url, graphVersion: 'gv-old' },
        }),
      ).toEqual({ contextIds: ['KRX:005930'], graphVersion: 'gv-old' });
    }
  });

  it('splits an impact path, keeps evidence and the pinned version, and sends no asOf the member did not set', () => {
    expect(
      contextFromTarget({
        kind: 'path',
        id: 'KRX:005930,iss-1',
        evidenceIds: ['ev-1', 'ev-1', 'ev-2'],
        mapContext: {
          url: '/',
          graphVersion: 'gv-2',
          asOf: '2026-10-21T00:00:00Z',
        },
      }),
    ).toEqual({
      contextIds: ['KRX:005930', 'iss-1'],
      evidenceIds: ['ev-1', 'ev-2'],
      graphVersion: 'gv-2',
    });
  });
});
