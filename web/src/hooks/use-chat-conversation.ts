import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import {
  cancelQuestionJob,
  createConversation,
  getConversation,
  getCurrentConversation,
  getQuestionJob,
  newChatId,
  retryQuestionJob,
  submitQuestion,
} from '@/apis/chat/chat';
import type {
  ChatChoice,
  ChatContextRequest,
  ChatConversation,
  ChatJob,
  ChatJobRequest,
} from '@/types/ai';
import type { GraphTarget } from '@/types/map';

// D-AI-01/01b/02/02b 대화 상태. 서버에 저장된 대화·작업만 표시하고 미검증 본문은 만들지 않는다.

export type ChatNotice = {
  tone: 'error' | 'info';
  message: string;
  code?: string | null;
  requestId?: string | null;
  /** 응답을 받지 못한 접수를 같은 jobId로 다시 보낼 수 있다(서버가 한 번만 처리). */
  resend?: boolean;
};

export type ChatLoad =
  { kind: 'loading' } | { kind: 'ready' } | { kind: 'error'; error: Error };

const ACTIVE = new Set(['queued', 'running']);
const POLL_FIRST_MS = 800;
const POLL_MS = 1500;
const MAX_QUESTION = 4000;
const MAX_IDS = 20;

export function isActive(job: ChatJob) {
  return ACTIVE.has(job.status);
}

/** 화면 선택 대상을 질문 문맥으로 옮긴다. 영향 경로(`path`)는 기업·사건 ID 둘로 나뉜다. */
export function contextFromTarget(target: GraphTarget): ChatContextRequest {
  const ids = target.kind === 'path' ? target.id.split(',') : [target.id];
  const context: ChatContextRequest = {
    contextIds: [...new Set(ids.filter(Boolean))].slice(0, MAX_IDS),
  };
  if (target.evidenceIds?.length)
    context.evidenceIds = [...new Set(target.evidenceIds)].slice(0, MAX_IDS);
  if (target.mapContext?.graphVersion)
    context.graphVersion = target.mapContext.graphVersion;
  return context;
}

export function questionLength(text: string) {
  return [...text].length;
}

export function isSendable(text: string) {
  const length = questionLength(text);
  return text.trim().length > 0 && length <= MAX_QUESTION;
}

function asError(error: unknown) {
  return error instanceof Error ? error : new Error(String(error));
}

/** 응답을 받지 못했거나 서버가 일시적으로 처리하지 못했다: 같은 요청을 다시 보내도 안전하다. */
function unanswered(error: unknown) {
  return (
    !(error instanceof ApiError) ||
    error.status === 0 ||
    error.status === 429 ||
    error.status >= 500
  );
}

function noticeFor(error: unknown, fallback: string): ChatNotice {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403)
      return {
        tone: 'error',
        message: '로그인이 필요하거나 이 대화에 접근할 수 없어요.',
        code: error.code,
        requestId: error.requestId,
      };
    return {
      tone: 'error',
      message: error.message || fallback,
      code: error.code,
      requestId: error.requestId,
      resend: unanswered(error),
    };
  }
  return { tone: 'error', message: fallback, resend: true };
}

function merge(jobs: ChatJob[], job: ChatJob) {
  const index = jobs.findIndex((item) => item.id === job.id);
  if (index < 0) return [...jobs, job].sort((a, b) => a.seq - b.seq);
  const next = jobs.slice();
  next[index] = job;
  return next;
}

/**
 * 회원의 최신 대화를 회수하고, 활성 작업을 polling하며, 질문·확인 답·재시도·취소를 보낸다.
 * 쓰는 컴포넌트는 회원 ID로 key를 주어 회원이 바뀌면 새로 시작한다. 그 전에 늦게 도착한 응답은 버린다.
 */
export function useChatConversation(memberId: string) {
  const [load, setLoad] = useState<ChatLoad>({ kind: 'loading' });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<ChatJob[]>([]);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<ChatNotice | null>(null);
  const [pollError, setPollError] = useState<Error | null>(null);
  const [pollRound, setPollRound] = useState(0);
  const generation = useRef(0);
  const unsent = useRef<{ sessionId: string; request: ChatJobRequest } | null>(
    null,
  );
  const actionKeys = useRef(new Map<string, string>());

  const apply = useCallback((conversation: ChatConversation | null) => {
    setSessionId(conversation?.session.id ?? null);
    setJobs(
      conversation ? [...conversation.jobs].sort((a, b) => a.seq - b.seq) : [],
    );
  }, []);

  const restore = useCallback(
    async (known: string | null) => {
      const current = generation.current;
      setLoad({ kind: 'loading' });
      try {
        const conversation = known
          ? await getConversation(known)
          : (await getCurrentConversation()).conversation;
        if (current !== generation.current) return;
        apply(conversation);
        setPollError(null);
        setLoad({ kind: 'ready' });
      } catch (error) {
        if (current !== generation.current) return;
        setLoad({ kind: 'error', error: asError(error) });
      }
    },
    [apply],
  );

  // 처음 열 때 최신 대화를 회수한다(새 모델 호출 아님). 상태는 응답 콜백에서만 바꾼다.
  useEffect(() => {
    const owner = generation;
    const current = owner.current;
    getCurrentConversation().then(
      ({ conversation }) => {
        if (current !== owner.current) return;
        apply(conversation);
        setLoad({ kind: 'ready' });
      },
      (error: unknown) => {
        if (current !== owner.current) return;
        setLoad({ kind: 'error', error: asError(error) });
      },
    );
    // 닫히거나 회원이 바뀌면 진행 중인 응답을 모두 버린다.
    return () => {
      owner.current += 1;
    };
  }, [memberId, apply]);

  const active = jobs.find(isActive) ?? null;
  const activeId = active?.id ?? null;

  // 활성 작업은 끝날 때까지 저장 상태만 다시 읽는다. 조회 실패는 polling을 멈추고 "다시 확인"을 기다린다.
  useEffect(() => {
    if (!activeId || pollError) return;
    const current = generation.current;
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const tick = async (delay: number) => {
      timer = setTimeout(async () => {
        try {
          const job = await getQuestionJob(activeId);
          if (stopped || current !== generation.current) return;
          setJobs((items) => merge(items, job));
          if (isActive(job)) void tick(POLL_MS);
        } catch (error) {
          if (stopped || current !== generation.current) return;
          setPollError(asError(error));
        }
      }, delay);
    };
    void tick(POLL_FIRST_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [activeId, pollError, pollRound]);

  const send = useCallback(
    async (request: ChatJobRequest, knownSession: string | null) => {
      const current = generation.current;
      setSending(true);
      setNotice(null);
      let session = knownSession;
      try {
        if (!session) {
          session = newChatId();
          await createConversation(session);
          if (current !== generation.current) return false;
          setSessionId(session);
        }
        unsent.current = { sessionId: session, request };
        const job = await submitQuestion(session, request);
        if (current !== generation.current) return false;
        unsent.current = null;
        setJobs((items) => merge(items, job));
        return true;
      } catch (error) {
        if (current !== generation.current) return false;
        if (error instanceof ApiError && error.code === 'JOB_IN_PROGRESS') {
          // 같은 대화의 활성 작업을 회수해 보여 주고 새 질문은 만들지 않는다.
          unsent.current = null;
          setNotice({
            tone: 'info',
            message:
              '이 대화에서 아직 처리 중인 질문이 있어요. 끝난 뒤에 다시 보내 주세요.',
          });
          void restore(session);
          return false;
        }
        const next = noticeFor(error, '질문을 보내지 못했어요.');
        if (!next.resend) unsent.current = null;
        if (request.resolves && error instanceof ApiError) {
          if (error.status === 404)
            next.message =
              '답하려던 확인 질문을 찾을 수 없어요. 새 질문으로 보내 주세요.';
          if (error.status === 422) void restore(session);
        }
        setNotice(next);
        return false;
      } finally {
        if (current === generation.current) setSending(false);
      }
    },
    [restore],
  );

  const ask = useCallback(
    (question: string, context: ChatContextRequest | null) => {
      if (!isSendable(question) || sending || active)
        return Promise.resolve(false);
      const request: ChatJobRequest = { jobId: newChatId(), question };
      if (context) request.context = context;
      return send(request, sessionId);
    },
    [active, send, sending, sessionId],
  );

  /** 확인 질문에 답한다. 선택지는 받은 id를 그대로, 자유 입력은 choiceId=null로 보낸다. */
  const reply = useCallback(
    (clarification: ChatJob, choice: ChatChoice | null, text?: string) => {
      const question = choice ? choice.label : (text ?? '');
      if (!isSendable(question) || sending || active)
        return Promise.resolve(false);
      return send(
        {
          jobId: newChatId(),
          question,
          resolves: {
            jobId: clarification.id,
            choiceId: choice ? choice.id : null,
          },
        },
        clarification.sessionId,
      );
    },
    [active, send, sending],
  );

  /** 응답을 받지 못한 접수를 같은 jobId로 다시 보낸다. */
  const resend = useCallback(() => {
    const pending = unsent.current;
    if (!pending || sending) return Promise.resolve(false);
    return send(pending.request, pending.sessionId);
  }, [send, sending]);

  const act = useCallback(async (job: ChatJob, kind: 'retry' | 'cancel') => {
    const current = generation.current;
    const slot = `${kind}:${job.id}`;
    const key = actionKeys.current.get(slot) ?? newChatId();
    actionKeys.current.set(slot, key);
    setNotice(null);
    try {
      const next =
        kind === 'retry'
          ? await retryQuestionJob(job.id, key)
          : await cancelQuestionJob(job.id, key);
      if (current !== generation.current) return;
      actionKeys.current.delete(slot);
      setPollError(null);
      setJobs((items) => merge(items, next));
    } catch (error) {
      if (current !== generation.current) return;
      if (!unanswered(error)) actionKeys.current.delete(slot);
      // 같은 버튼을 다시 누르면 같은 키로 보낸다. 질문 재전송과는 구분한다.
      setNotice({
        ...noticeFor(
          error,
          kind === 'retry' ? '다시 처리하지 못했어요.' : '취소하지 못했어요.',
        ),
        resend: false,
      });
    }
  }, []);

  /** 새 대화. 실패하면 기존 대화를 그대로 둔다. */
  const startNew = useCallback(async () => {
    const current = generation.current;
    const id = newChatId();
    setNotice(null);
    try {
      await createConversation(id);
      if (current !== generation.current) return;
      unsent.current = null;
      setSessionId(id);
      setJobs([]);
      setPollError(null);
      setLoad({ kind: 'ready' });
    } catch (error) {
      if (current !== generation.current) return;
      setNotice(noticeFor(error, '새 대화를 만들지 못했어요.'));
    }
  }, []);

  /** "다시 확인": 저장 상태만 다시 읽는다. 모델을 다시 부르지 않는다. */
  const recheck = useCallback(() => {
    if (load.kind === 'error') return restore(sessionId);
    setPollError(null);
    setPollRound((value) => value + 1);
    return Promise.resolve();
  }, [load.kind, restore, sessionId]);

  return {
    load,
    sessionId,
    jobs,
    active,
    sending,
    notice,
    pollError,
    hasUnsent: notice?.resend === true,
    ask,
    reply,
    resend,
    retry: (job: ChatJob) => act(job, 'retry'),
    cancel: (job: ChatJob) => act(job, 'cancel'),
    startNew,
    recheck,
    dismissNotice: () => setNotice(null),
  };
}

export type ChatConversationState = ReturnType<typeof useChatConversation>;
export { MAX_QUESTION };
