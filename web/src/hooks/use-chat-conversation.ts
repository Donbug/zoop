import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { exactTime } from '@/components/company/detail-model';
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
};

export type ChatLoad =
  { kind: 'loading' } | { kind: 'ready' } | { kind: 'error'; error: Error };

/**
 * 응답을 받지 못한 질문. 서버가 접수했는지 모르므로 같은 대화 ID·jobId로만 다시 보내거나(서버가 한 번만 처리),
 * 명시적으로 버린다. 남아 있는 동안 다른 질문은 보내지 않는다.
 */
export type PendingQuestion = {
  sessionId: string;
  /** 대화 생성(PUT)이 확인됐는지. 아니면 다시 보낼 때 같은 ID로 먼저 만든다. */
  sessionReady: boolean;
  request: ChatJobRequest;
};

const ACTIVE = new Set(['queued', 'running']);
const POLL_FIRST_MS = 800;
const POLL_MS = 1500;
const MAX_QUESTION = 4000;
const MAX_IDS = 20;

export function isActive(job: ChatJob) {
  return ACTIVE.has(job.status);
}

/**
 * 화면 선택 대상을 질문 문맥으로 옮긴다. 영향 경로(`path`)는 기업·사건 ID 둘로 나뉜다. 그래프 버전은 화면이 보여 준
 * 버전으로 고정하고, 기준 시각(`asOf`)은 회원이 지도 주소에 명시했을 때만 보낸다(응답 메타데이터의 시각은 cutoff가 아니다).
 */
export function contextFromTarget(target: GraphTarget): ChatContextRequest {
  const ids = target.kind === 'path' ? target.id.split(',') : [target.id];
  const context: ChatContextRequest = {
    contextIds: [...new Set(ids.filter(Boolean))].slice(0, MAX_IDS),
  };
  if (target.evidenceIds?.length)
    context.evidenceIds = [...new Set(target.evidenceIds)].slice(0, MAX_IDS);
  if (target.mapContext?.graphVersion)
    context.graphVersion = target.mapContext.graphVersion;
  const asOf = requestedAsOf(target.mapContext?.url);
  if (asOf) context.asOf = asOf;
  return context;
}

/** 지도가 실제로 적용한 기준 시각만: 지도와 같이 기업 지도(companyId)의 정확한 시각(시간대 포함)일 때다. */
function requestedAsOf(url: string | undefined) {
  if (!url) return null;
  const query = new URLSearchParams(
    url.includes('?') ? url.slice(url.indexOf('?') + 1) : '',
  );
  const value = query.get('asOf');
  return query.get('companyId') && exactTime(value) ? value : null;
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

/**
 * 접수됐는지 알 수 없다: 응답을 받지 못했거나(네트워크·408), 일시적으로 처리하지 못했거나(429·5xx), 성공 상태의 본문을
 * 읽지 못했다(INVALID_RESPONSE). 같은 ID·키로 다시 보내야 하며, 그 밖의 4xx만 확정 거절이다.
 */
function unanswered(error: unknown) {
  return (
    !(error instanceof ApiError) ||
    error.status === 0 ||
    error.status === 408 ||
    error.status === 429 ||
    error.status >= 500 ||
    error.code === 'INVALID_RESPONSE'
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
    };
  }
  return { tone: 'error', message: fallback };
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
 *
 * - 쓰는 컴포넌트는 회원 ID로 key를 주어 회원이 바뀌면 새로 시작한다. 닫히거나 바뀌기 전에 늦게 도착한 응답은 버린다.
 * - 새 대화로 바꾸는 데 성공하면 대화 epoch가 바뀌어, 이전 대화의 복원·polling·재시도·취소 응답은 반영하지 않는다.
 *   응답 작업도 지금 대화의 것만 반영한다. 새 대화를 만들지 못하면 기존 대화를 그대로 둔다.
 */
export function useChatConversation(memberId: string) {
  const [load, setLoad] = useState<ChatLoad>({ kind: 'loading' });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<ChatJob[]>([]);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<ChatNotice | null>(null);
  const [pending, setPending] = useState<PendingQuestion | null>(null);
  const [pollError, setPollError] = useState<Error | null>(null);
  const [pollRound, setPollRound] = useState(0);
  const [switching, setSwitching] = useState(false);
  const [acting, setActing] = useState(0);
  const generation = useRef(0);
  const epoch = useRef(0);
  const session = useRef<string | null>(null);
  const actionKeys = useRef(new Map<string, string>());

  /** 지금 시작하는 비동기 작업의 표식. 응답이 왔을 때 같은 회원·같은 대화인지 확인한다. */
  const mark = useCallback(
    () => ({ generation: generation.current, epoch: epoch.current }),
    [],
  );
  const current = useCallback(
    (stamp: { generation: number; epoch: number }) =>
      stamp.generation === generation.current && stamp.epoch === epoch.current,
    [],
  );

  const adopt = useCallback((id: string | null) => {
    session.current = id;
    setSessionId(id);
  }, []);

  /** 지금 대화의 작업일 때만 반영한다. */
  const accept = useCallback((job: ChatJob) => {
    setJobs((items) =>
      job.sessionId === session.current ? merge(items, job) : items,
    );
  }, []);

  const apply = useCallback(
    (conversation: ChatConversation | null) => {
      adopt(conversation?.session.id ?? null);
      setJobs(
        conversation
          ? [...conversation.jobs].sort((a, b) => a.seq - b.seq)
          : [],
      );
    },
    [adopt],
  );

  const restore = useCallback(
    async (known: string | null) => {
      const stamp = mark();
      setLoad({ kind: 'loading' });
      try {
        const conversation = known
          ? await getConversation(known)
          : (await getCurrentConversation()).conversation;
        if (!current(stamp)) return;
        apply(conversation);
        setPollError(null);
        setLoad({ kind: 'ready' });
      } catch (error) {
        if (!current(stamp)) return;
        setLoad({ kind: 'error', error: asError(error) });
      }
    },
    [apply, current, mark],
  );

  // 처음 열 때 최신 대화를 회수한다(새 모델 호출 아님). 상태는 응답 콜백에서만 바꾼다.
  useEffect(() => {
    const owner = generation;
    const stamp = { generation: owner.current, epoch: epoch.current };
    getCurrentConversation().then(
      ({ conversation }) => {
        if (stamp.generation !== owner.current || stamp.epoch !== epoch.current)
          return;
        apply(conversation);
        setLoad({ kind: 'ready' });
      },
      (error: unknown) => {
        if (stamp.generation !== owner.current || stamp.epoch !== epoch.current)
          return;
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
    const stamp = mark();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const tick = async (delay: number) => {
      timer = setTimeout(async () => {
        try {
          const job = await getQuestionJob(activeId);
          if (stopped || !current(stamp)) return;
          accept(job);
          if (isActive(job)) void tick(POLL_MS);
        } catch (error) {
          if (stopped || !current(stamp)) return;
          setPollError(asError(error));
        }
      }, delay);
    };
    void tick(POLL_FIRST_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [activeId, pollError, pollRound, accept, current, mark]);

  /** 미확정 질문을 보낸다. 대화가 아직 확인되지 않았으면 같은 ID로 먼저 만든다(PUT은 멱등). */
  const deliver = useCallback(
    async (question: PendingQuestion) => {
      const stamp = mark();
      setSending(true);
      setNotice(null);
      setPending(question);
      let state = question;
      try {
        if (!state.sessionReady) {
          await createConversation(state.sessionId);
          if (!current(stamp)) return false;
          state = { ...state, sessionReady: true };
          setPending(state);
          if (session.current === null) adopt(state.sessionId);
        }
        const job = await submitQuestion(state.sessionId, state.request);
        if (!current(stamp)) return false;
        setPending(null);
        accept(job);
        return true;
      } catch (error) {
        if (!current(stamp)) return false;
        if (error instanceof ApiError && error.code === 'JOB_IN_PROGRESS') {
          // 같은 대화의 활성 작업을 회수해 보여 주고 새 질문은 만들지 않는다.
          setPending(null);
          setNotice({
            tone: 'info',
            message:
              '이 대화에서 아직 처리 중인 질문이 있어요. 끝난 뒤에 다시 보내 주세요.',
          });
          void restore(state.sessionId);
          return false;
        }
        const next = noticeFor(error, '질문을 보내지 못했어요.');
        // 확정적으로 거절된 질문(4xx)은 서버에 없다: 미확정 상태로 남기지 않는다.
        if (!unanswered(error)) setPending(null);
        if (state.request.resolves && error instanceof ApiError) {
          if (error.status === 404)
            next.message =
              '답하려던 확인 질문을 찾을 수 없어요. 새 질문으로 보내 주세요.';
          if (error.status === 422) void restore(state.sessionId);
        }
        setNotice(next);
        return false;
      } finally {
        if (current(stamp)) setSending(false);
      }
    },
    [accept, adopt, current, mark, restore],
  );

  const blocked = sending || switching || active !== null || pending !== null;

  const ask = useCallback(
    (question: string, context: ChatContextRequest | null) => {
      if (!isSendable(question) || blocked) return Promise.resolve(false);
      const request: ChatJobRequest = { jobId: newChatId(), question };
      if (context) request.context = context;
      return deliver(
        sessionId
          ? { sessionId, sessionReady: true, request }
          : { sessionId: newChatId(), sessionReady: false, request },
      );
    },
    [blocked, deliver, sessionId],
  );

  /** 확인 질문에 답한다. 선택지는 받은 id를 그대로, 자유 입력은 choiceId=null로 보낸다. */
  const reply = useCallback(
    (clarification: ChatJob, choice: ChatChoice | null, text?: string) => {
      const question = choice ? choice.label : (text ?? '');
      if (!isSendable(question) || blocked) return Promise.resolve(false);
      return deliver({
        sessionId: clarification.sessionId,
        sessionReady: true,
        request: {
          jobId: newChatId(),
          question,
          resolves: {
            jobId: clarification.id,
            choiceId: choice ? choice.id : null,
          },
        },
      });
    },
    [blocked, deliver],
  );

  /** 미확정 질문을 같은 대화 ID·jobId로 다시 보낸다. */
  const resend = useCallback(() => {
    if (!pending || sending) return Promise.resolve(false);
    return deliver(pending);
  }, [deliver, pending, sending]);

  /** 미확정 질문을 버린다. 서버가 이미 받았을 수 있으므로 대화를 다시 읽어 실제 상태를 보여 준다. */
  const discard = useCallback(() => {
    if (!pending || sending) return Promise.resolve();
    const known = session.current;
    setPending(null);
    setNotice(null);
    return known ? restore(known) : Promise.resolve();
  }, [pending, restore, sending]);

  const act = useCallback(
    async (job: ChatJob, kind: 'retry' | 'cancel') => {
      if (switching) return;
      const stamp = mark();
      const slot = `${kind}:${job.id}`;
      const key = actionKeys.current.get(slot) ?? newChatId();
      actionKeys.current.set(slot, key);
      setNotice(null);
      setActing((count) => count + 1);
      try {
        const next =
          kind === 'retry'
            ? await retryQuestionJob(job.id, key)
            : await cancelQuestionJob(job.id, key);
        if (!current(stamp)) return;
        actionKeys.current.delete(slot);
        setPollError(null);
        accept(next);
      } catch (error) {
        if (!current(stamp)) return;
        if (!unanswered(error)) actionKeys.current.delete(slot);
        // 같은 버튼을 다시 누르면 같은 키로 보낸다.
        setNotice(
          noticeFor(
            error,
            kind === 'retry' ? '다시 처리하지 못했어요.' : '취소하지 못했어요.',
          ),
        );
      } finally {
        if (stamp.generation === generation.current)
          setActing((count) => count - 1);
      }
    },
    [accept, current, mark, switching],
  );

  /**
   * 새 대화. 보내는 중·재시도/취소 중이거나 접수를 확인하지 못한 질문이 있으면 시작하지 않는다(그 질문을 다시 보내거나
   * 버린 뒤 시작한다). 만드는 동안에는 전송·재시도·취소를 막는다. 성공하면 이전 대화의 늦은 응답을 모두 버리고, 실패하면
   * 기존 대화를 그대로 둔다.
   */
  const canSwitch = !sending && !switching && acting === 0 && pending === null;
  const startNew = useCallback(async () => {
    if (!canSwitch) return false;
    const stamp = mark();
    const id = newChatId();
    setNotice(null);
    setSwitching(true);
    try {
      await createConversation(id);
      if (!current(stamp)) return false;
      epoch.current += 1;
      adopt(id);
      setJobs([]);
      setPollError(null);
      setLoad({ kind: 'ready' });
      return true;
    } catch (error) {
      if (!current(stamp)) return false;
      setNotice(noticeFor(error, '새 대화를 만들지 못했어요.'));
      return false;
    } finally {
      // 성공하면 epoch가 바뀌므로 같은 회원인지만 본다.
      if (stamp.generation === generation.current) setSwitching(false);
    }
  }, [adopt, canSwitch, current, mark]);

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
    switching,
    acting: acting > 0,
    canSwitch,
    notice,
    // 보내는 동안은 아직 결과를 모르는 것이지 접수를 확인하지 못한 것이 아니다: 실패한 뒤에만 미확정으로 보여 준다.
    pending: sending ? null : pending,
    pollError,
    ask,
    reply,
    resend,
    discard,
    retry: (job: ChatJob) => act(job, 'retry'),
    cancel: (job: ChatJob) => act(job, 'cancel'),
    startNew,
    recheck,
    dismissNotice: () => setNotice(null),
  };
}

export type ChatConversationState = ReturnType<typeof useChatConversation>;
export { MAX_QUESTION };
