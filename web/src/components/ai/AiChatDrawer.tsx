import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { Link, useLocation } from 'react-router-dom';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import ChatHistoryList from '@/components/ai/ChatHistoryList';
import ChatJobCard, { type AnswerMapTarget } from '@/components/ai/ChatJobCard';
import { PHASE_LABEL } from '@/components/ai/chat-phases';
import {
  contextFromTarget,
  isSendable,
  MAX_QUESTION,
  questionLength,
  useChatConversation,
  type ChatNotice,
  type PendingQuestion,
} from '@/hooks/use-chat-conversation';
import { useAuth } from '@/hooks/useAuth';
import { useAiChatStore } from '@/stores/useAiChatStore';
import type { ChatJob } from '@/types/ai';
import type { GraphTarget } from '@/types/map';

// D-AI-01 질문·대상 연결, D-AI-01b 확인 질문, D-AI-02 작업 복구·대화 회수(대화 기록 포함), D-AI-02b 대화 조회 오류.
// 상태 계약: docs/wireframe/ai-chatbot-state-contract.md

const TARGET_KIND: Record<GraphTarget['kind'], string> = {
  company: '기업',
  issue: '사건',
  edge: '관계',
  path: '영향 경로',
};

type Props = {
  /** 답변이 가리키는 대상을 답변의 그래프 버전 기준으로 지도에 연다. 열 수 없으면 false. */
  onViewOnMap?: (target: AnswerMapTarget) => boolean;
  /** 닫을 때 연 요소가 더는 없으면(다른 화면 헤더에서 열고 지도로 이동한 경우) 포커스를 돌려줄 지도 영역. */
  returnFocusTo?: RefObject<HTMLElement | null>;
};

export default function AiChatDrawer({ onViewOnMap, returnFocusTo }: Props) {
  const isOpen = useAiChatStore((state) => state.isOpen);
  const close = useAiChatStore((state) => state.close);
  const { checking, isAuthenticated, member } = useAuth();
  const location = useLocation();
  if (!isOpen) return null;
  return (
    <DrawerShell onClose={close} returnFocusTo={returnFocusTo}>
      {checking ? (
        <p className={ui.state} role="status">
          로그인 상태를 확인하고 있어요.
        </p>
      ) : isAuthenticated && member ? (
        <ChatPanel
          key={member.id}
          memberId={member.id}
          onViewOnMap={onViewOnMap}
        />
      ) : (
        <div className={ui.state}>
          <p className="mt-0!">AI 질문은 회원만 쓸 수 있어요.</p>
          <Link
            to="/login"
            state={{ from: `${location.pathname}${location.search}` }}
            className="underline"
          >
            로그인 후 질문하기
          </Link>
        </div>
      )}
    </DrawerShell>
  );
}

function DrawerShell({
  onClose,
  returnFocusTo,
  children,
}: {
  onClose: () => void;
  returnFocusTo?: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => heading.current?.focus());
    const returnTo = opener;
    const fallback = returnFocusTo;
    return () => {
      cancelAnimationFrame(frame);
      const target = returnTo.current;
      // The opener may be gone: a header on another screen opened the drawer and unmounted on the way to the map.
      if (target && target !== document.body && target.isConnected)
        target.focus();
      else fallback?.current?.focus();
    };
  }, [returnFocusTo]);

  return (
    <div className="absolute inset-0 z-20 flex justify-end">
      <div
        className="absolute inset-0 bg-black/35"
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        ref={dialog}
        className={`${ui.shell} relative w-[440px]! max-w-full shadow-[0_25px_50px_-12px_rgb(0_0_0/0.25)]`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-chat-title"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation();
            onClose();
            return;
          }
          if (event.key !== 'Tab') return;
          const focusable = dialog.current?.querySelectorAll<HTMLElement>(
            'button:not([disabled]), a[href], textarea:not([disabled]), input:not([disabled]), summary, [tabindex="0"]',
          );
          if (!focusable?.length) return;
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (
            event.shiftKey &&
            (document.activeElement === first ||
              document.activeElement === heading.current)
          ) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <header className={`${ui.header} border-b border-panel-line`}>
          <h2
            id="ai-chat-title"
            ref={heading}
            tabIndex={-1}
            className={`${ui.title} outline-none`}
          >
            AI에게 묻기
          </h2>
          <button
            type="button"
            className={`absolute top-4 right-4 ${ui.close}`}
            aria-label="AI 질문 창 닫기"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        {children}
      </aside>
    </div>
  );
}

function ChatPanel({
  memberId,
  onViewOnMap,
}: {
  memberId: string;
  onViewOnMap?: Props['onViewOnMap'];
}) {
  const target = useAiChatStore((state) => state.context);
  const draft = useAiChatStore((state) => state.draft);
  const setDraft = useAiChatStore((state) => state.setDraft);
  const chat = useChatConversation(memberId);
  const [linked, setLinked] = useState(true);
  const [replyTo, setReplyTo] = useState<ChatJob | null>(null);
  const [view, setView] = useState<'chat' | 'history'>('chat');
  const input = useRef<HTMLTextAreaElement>(null);

  const useTarget = linked && target !== null;
  const targetLabel = target ? (target.label ?? target.id) : null;
  const locked =
    chat.load.kind !== 'ready' ||
    chat.sending ||
    chat.switching ||
    chat.active !== null ||
    chat.pending !== null;
  const sendable = isSendable(draft) && !locked;
  const length = questionLength(draft);

  async function submit() {
    if (!sendable) return;
    const sent = replyTo
      ? await chat.reply(replyTo, null, draft)
      : await chat.ask(draft, useTarget ? contextFromTarget(target) : null);
    if (sent) {
      setDraft('');
      setReplyTo(null);
    }
  }

  /**
   * 미확정 질문을 다시 보내 접수되면 그 질문의 입력과 답할 확인 질문을 비운다. 기다리는 동안 새로 입력한 글이나 다른 확인
   * 질문은 그대로 둔다.
   */
  async function resend() {
    const sent = chat.pending?.request;
    if (!sent || !(await chat.resend())) return;
    if (useAiChatStore.getState().draft === sent.question) setDraft('');
    setReplyTo((current) =>
      current && current.id === sent.resolves?.jobId ? null : current,
    );
  }

  async function startNew() {
    if (await chat.startNew()) {
      setReplyTo(null);
      setView('chat');
    }
  }

  async function open(id: string) {
    const changed = id !== chat.sessionId;
    // 열지 못하면 질문 창으로 돌아가 오류 안내를 보여 준다. 대화는 그대로다.
    const opened = await chat.open(id);
    if (opened && changed) setReplyTo(null);
    setView('chat');
  }

  const byId = new Map(chat.jobs.map((job) => [job.id, job]));
  // 안내할 작업: 진행 중인 작업(재시도한 이전 작업일 수 있음), 없으면 가장 최근에 바뀐 작업.
  const announced =
    chat.active ??
    [...chat.jobs]
      .sort((a, b) => a.updatedAt.localeCompare(b.updatedAt))
      .at(-1);

  return (
    <>
      <div className="flex shrink-0 items-center justify-between gap-2 px-4 py-2">
        <p className={ui.muted}>
          질문 대상: {useTarget ? targetLabel : '없음'}
        </p>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            className={ui.button}
            aria-pressed={view === 'history'}
            onClick={() => setView(view === 'history' ? 'chat' : 'history')}
          >
            대화 기록
          </button>
          <button
            type="button"
            className={ui.button}
            disabled={!chat.canSwitch}
            onClick={() => void startNew()}
          >
            새 대화
          </button>
        </div>
      </div>
      {view === 'history' ? (
        <ChatHistoryList
          currentId={chat.sessionId}
          canOpen={chat.canSwitch}
          onOpen={(id) => void open(id)}
          onDeleted={(id) => {
            if (id === chat.sessionId) setReplyTo(null);
            chat.forget(id);
          }}
          onBack={() => setView('chat')}
        />
      ) : (
        <>
          <div className={ui.scroll}>
            <section className={ui.section} aria-labelledby="ai-chat-target">
              <h3 id="ai-chat-target">질문에 연결할 대상</h3>
              {target ? (
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={linked}
                    onChange={(event) => setLinked(event.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    <span className={ui.itemTitle}>{targetLabel}</span>
                    <span className={`${ui.muted} block`}>
                      {TARGET_KIND[target.kind]}
                      {target.evidenceIds?.length
                        ? ` · 근거 ${target.evidenceIds.length}건`
                        : ''}
                      {target.mapContext?.graphVersion
                        ? ` · 그래프 ${target.mapContext.graphVersion}`
                        : ''}
                    </span>
                  </span>
                </label>
              ) : (
                <p className={ui.muted}>
                  지도에서 기업이나 사건을 고르면 질문에 연결할 수 있어요.
                </p>
              )}
            </section>

            <div aria-live="polite" className="sr-only">
              {announced ? statusText(announced) : ''}
            </div>

            {chat.load.kind === 'loading' && (
              <p className={ui.state} role="status">
                이전 대화를 불러오고 있어요.
              </p>
            )}
            {chat.load.kind === 'error' && (
              <LoadError
                error={chat.load.error}
                onRecheck={() => void chat.recheck()}
                onNew={() => void startNew()}
              />
            )}
            {chat.load.kind === 'ready' && chat.jobs.length === 0 && (
              <p className={ui.state}>
                궁금한 점을 입력해 보세요. 일반 개념은 바로 물을 수 있고, “그
                기업”처럼 대상을 가리키는 질문은 어떤 대상인지 되물을 수 있어요.
              </p>
            )}
            {chat.jobs.map((job) => (
              <ChatJobCard
                key={job.id}
                job={job}
                answers={
                  job.resolves ? (byId.get(job.resolves.jobId) ?? null) : null
                }
                busy={locked || chat.acting}
                onChoose={(clarification, choice) =>
                  void chat.reply(clarification, choice)
                }
                onAnswerFreely={(clarification) => {
                  setReplyTo(clarification);
                  input.current?.focus();
                }}
                onRetry={(job) => void chat.retry(job)}
                onCancel={(job) => void chat.cancel(job)}
                onViewOnMap={onViewOnMap}
              />
            ))}
            {chat.pollError && (
              <div className={ui.state} role="alert">
                <p className="mt-0!">
                  질문 상태를 확인하지 못했어요. 질문은 서버에서 계속 처리되고
                  있을 수 있어요.
                </p>
                <button type="button" onClick={() => void chat.recheck()}>
                  다시 확인
                </button>
              </div>
            )}
            {chat.pending && (
              <PendingBox
                pending={chat.pending}
                busy={chat.sending}
                onResend={() => void resend()}
                onDiscard={() => void chat.discard()}
              />
            )}
            {chat.notice && (
              <NoticeBox notice={chat.notice} onDismiss={chat.dismissNotice} />
            )}
          </div>

          <form
            className="shrink-0 border-t border-panel-line px-4 py-3"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            {replyTo && (
              <p
                className={`${ui.muted} mb-2 flex items-center justify-between gap-2`}
              >
                <span className="wrap-anywhere">
                  확인 질문 “{replyTo.question}”에 답하는 중
                </span>
                <button
                  type="button"
                  className="underline"
                  onClick={() => setReplyTo(null)}
                >
                  답하지 않기
                </button>
              </p>
            )}
            <div className="flex items-end gap-2">
              <label className="sr-only" htmlFor="ai-chat-input">
                질문
              </label>
              <textarea
                id="ai-chat-input"
                ref={input}
                rows={2}
                className="min-h-10 flex-1 resize-none rounded-panel border border-panel-line px-3 py-2 text-[12px] leading-[18px] focus-visible:outline-2 focus-visible:outline-panel-ink"
                placeholder="질문을 입력해 주세요"
                value={draft}
                aria-describedby="ai-chat-hint"
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === 'Enter' &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void submit();
                  }
                }}
              />
              <button
                type="submit"
                className={ui.button}
                disabled={!sendable}
                aria-busy={chat.sending}
              >
                {chat.sending ? '보내는 중' : '보내기'}
              </button>
            </div>
            <div id="ai-chat-hint" className={`${ui.muted} mt-1`}>
              {chat.active && (
                <p className="m-0">
                  이 대화의 질문을 처리하는 동안에는 새 질문을 보낼 수 없어요.
                </p>
              )}
              {!useTarget && !replyTo && (
                <p className="m-0">
                  연결한 대상이 없어요. 질문에 기업 이름을 적거나 위에서 대상을
                  골라 주세요.
                </p>
              )}
              {length > MAX_QUESTION - 500 && (
                <p
                  className={
                    length > MAX_QUESTION ? 'm-0 text-zoop-alert' : 'm-0'
                  }
                >
                  {length}/{MAX_QUESTION}자
                </p>
              )}
              <p className="m-0">AI가 생성한 답변이며 투자 권유가 아니에요.</p>
            </div>
          </form>
        </>
      )}
    </>
  );
}

function statusText(job: ChatJob) {
  if (job.status === 'queued') return '질문을 접수했어요.';
  if (job.status === 'running')
    return job.phase
      ? `답변을 준비하고 있어요. 지금 단계: ${PHASE_LABEL[job.phase]}`
      : '답변을 준비하고 있어요.';
  if (job.status === 'failed') return '질문을 처리하지 못했어요.';
  if (job.status === 'cancelled') return '질문을 취소했어요.';
  if (job.result?.outcome === 'clarification') return '확인 질문이 도착했어요.';
  return '답변이 도착했어요.';
}

function errorDetails(error: {
  code?: string | null;
  requestId?: string | null;
}) {
  return [
    error.code && `오류 코드 ${error.code}`,
    error.requestId && `요청 ID ${error.requestId}`,
  ]
    .filter(Boolean)
    .join(' · ');
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(
          () => setCopied(true),
          () => setCopied(false),
        );
      }}
    >
      {copied ? '복사했어요' : '오류 정보 복사'}
    </button>
  );
}

// D-AI-02b: 대화 회수 GET 실패. AI 작업 실패와 구분하고, "다시 확인"은 조회만 다시 한다.
function LoadError({
  error,
  onRecheck,
  onNew,
}: {
  error: Error;
  onRecheck: () => void;
  onNew: () => void;
}) {
  const details = errorDetails(
    error as { code?: string | null; requestId?: string | null },
  );
  const denied =
    'status' in error &&
    ((error as { status: number }).status === 401 ||
      (error as { status: number }).status === 403);
  return (
    <div className={ui.state} role="alert">
      <strong>
        {denied ? '이 대화에 접근할 수 없어요.' : '대화를 불러오지 못했어요.'}
      </strong>
      <p>
        {denied
          ? '로그인 상태를 확인한 뒤 다시 열어 주세요.'
          : '이전 대화와 질문 상태는 서버에 남아 있어요. 다시 확인해도 질문을 새로 처리하지 않아요.'}
      </p>
      {details && <p className={ui.muted}>{details}</p>}
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={onRecheck}>
          다시 확인
        </button>
        {details && <CopyButton text={details} />}
        <button type="button" onClick={onNew}>
          새 대화
        </button>
      </div>
    </div>
  );
}

// 응답을 받지 못한 질문: 서버가 받았는지 모르므로 같은 질문으로만 다시 보내거나, 버리고 새로 쓴다.
function PendingBox({
  pending,
  busy,
  onResend,
  onDiscard,
}: {
  pending: PendingQuestion;
  busy: boolean;
  onResend: () => void;
  onDiscard: () => void;
}) {
  return (
    <div className={ui.state} role="status">
      <p className="mt-0!">
        “{pending.request.question}” 질문이 접수됐는지 확인하지 못했어요. 같은
        질문으로 다시 보내면 한 번만 처리돼요.
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="button" disabled={busy} onClick={onResend}>
          같은 질문 다시 보내기
        </button>
        <button type="button" disabled={busy} onClick={onDiscard}>
          보내지 않은 것으로 하기
        </button>
      </div>
    </div>
  );
}

function NoticeBox({
  notice,
  onDismiss,
}: {
  notice: ChatNotice;
  onDismiss: () => void;
}) {
  const details = errorDetails(notice);
  return (
    <div
      className={ui.state}
      role={notice.tone === 'error' ? 'alert' : 'status'}
    >
      <p className="mt-0!">{notice.message}</p>
      {details && <p className={ui.muted}>{details}</p>}
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={onDismiss}>
          닫기
        </button>
      </div>
    </div>
  );
}
