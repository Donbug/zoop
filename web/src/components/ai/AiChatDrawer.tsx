import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { Link, useLocation } from 'react-router-dom';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import LoadingIndicator from '@/components/common/LoadingIndicator';
import ChatHistoryList from '@/components/ai/ChatHistoryList';
import ChatJobCard, { type AnswerMapTarget } from '@/components/ai/ChatJobCard';
import { PHASE_LABEL } from '@/components/ai/chat-phases';
import {
  contextFromTargets,
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

type LinkedTarget = { target: GraphTarget; checked: boolean };
const targetLabel = (target: GraphTarget) => target.label ?? target.id;
const sameTarget = (a: GraphTarget, b: GraphTarget) =>
  a.kind === b.kind && a.id === b.id;

// D-AI-01 · prototype chat-drawer.tsx:41: 빈 대화의 추천 질문. 세 번째는 예측을 묻는 질문이라 서버가 답을 지어내지 않고 보류하는지 보여 준다.
const SUGGESTIONS = [
  '함께 언급된 기업은 어디인가요?',
  '이 사건은 언제, 어떤 보도로 알려졌나요?',
  '이 사건 이후 주가 전망은 어떤가요?',
];

type Props = {
  /** 답변이 가리키는 대상을 답변의 그래프 버전 기준으로 지도에 연다. 열 수 없으면 false. */
  onViewOnMap?: (target: AnswerMapTarget) => boolean;
  /** 닫을 때 연 요소가 더는 없으면(다른 화면 헤더에서 열고 지도로 이동한 경우) 포커스를 돌려줄 지도 영역. */
  returnFocusTo?: RefObject<HTMLElement | null>;
};

export default function AiChatDrawer({ onViewOnMap, returnFocusTo }: Props) {
  const isOpen = useAiChatStore((state) => state.isOpen);
  const close = useAiChatStore((state) => state.close);
  const [showHistory, setShowHistory] = useState(false);
  const { checking, isAuthenticated, member } = useAuth();
  const location = useLocation();
  if (!isOpen) return null;
  return (
    <DrawerShell
      onClose={() => {
        setShowHistory(false);
        close();
      }}
      returnFocusTo={returnFocusTo}
      showHistory={showHistory}
    >
      {checking ? (
        <LoadingIndicator
          label="로그인 상태를 확인하고 있어요."
          className={`${ui.state} flex min-h-12 w-full`}
        />
      ) : isAuthenticated && member ? (
        <ChatPanel
          key={member.id}
          memberId={member.id}
          onViewOnMap={onViewOnMap}
          onHistoryViewChange={setShowHistory}
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
  showHistory,
  children,
}: {
  onClose: () => void;
  returnFocusTo?: RefObject<HTMLElement | null>;
  showHistory: boolean;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const resizeStart = useRef<{
    pointerId: number;
    x: number;
    width: number;
  } | null>(null);
  const [width, setWidth] = useState(440);

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
        className={`${ui.shell} relative max-w-full shadow-[0_25px_50px_-12px_rgb(0_0_0/0.25)]`}
        style={{ width: `${width}px` }}
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
        <div
          role="separator"
          aria-label="챗봇 패널 너비 조절"
          aria-orientation="vertical"
          aria-valuemin={320}
          aria-valuemax={720}
          aria-valuenow={width}
          tabIndex={0}
          className="absolute top-0 bottom-0 left-0 z-20 w-1.5 cursor-col-resize touch-none focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-panel-control"
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            resizeStart.current = {
              pointerId: event.pointerId,
              x: event.clientX,
              width,
            };
          }}
          onPointerMove={(event) => {
            const start = resizeStart.current;
            if (!start || start.pointerId !== event.pointerId) return;
            const max = Math.max(320, Math.min(720, window.innerWidth - 24));
            setWidth(
              Math.max(
                320,
                Math.min(max, start.width + start.x - event.clientX),
              ),
            );
          }}
          onPointerUp={(event) => {
            if (resizeStart.current?.pointerId === event.pointerId)
              resizeStart.current = null;
          }}
          onPointerCancel={() => {
            resizeStart.current = null;
          }}
          onKeyDown={(event) => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            event.preventDefault();
            const direction = event.key === 'ArrowLeft' ? 1 : -1;
            const max = Math.max(320, Math.min(720, window.innerWidth - 24));
            setWidth((current) =>
              Math.max(320, Math.min(max, current + direction * 24)),
            );
          }}
        />
        <header className="relative flex shrink-0 justify-end px-4 pt-3 pb-1">
          <h2
            id="ai-chat-title"
            ref={heading}
            tabIndex={-1}
            className="absolute top-5 left-14 text-body font-semibold leading-5 text-panel-ink"
          >
            {showHistory ? (
              '대화 기록'
            ) : (
              <span className="relative inline-flex items-center">
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  className="absolute -left-10 top-1/2 size-[18px] -translate-y-1/2"
                  fill="none"
                >
                  <path
                    d="M5 5.5h14A1.5 1.5 0 0 1 20.5 7v9a1.5 1.5 0 0 1-1.5 1.5h-7L7 21v-3.5H5A1.5 1.5 0 0 1 3.5 16V7A1.5 1.5 0 0 1 5 5.5Z"
                    stroke="currentColor"
                    strokeLinejoin="round"
                    strokeWidth="1.6"
                  />
                  <path
                    d="M8 10h8M8 13h5"
                    stroke="currentColor"
                    strokeLinecap="round"
                    strokeWidth="1.5"
                  />
                </svg>
                채팅
              </span>
            )}
          </h2>
          <button
            type="button"
            className="grid size-9 shrink-0 place-items-center rounded-full text-panel-secondary transition-colors hover:bg-panel-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-panel-ink"
            aria-label="AI 질문 창 닫기"
            onClick={onClose}
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="size-6"
              fill="none"
            >
              <path
                d="m6 6 12 12M18 6 6 18"
                stroke="currentColor"
                strokeLinecap="round"
                strokeWidth="1.8"
              />
            </svg>
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
  onHistoryViewChange,
}: {
  memberId: string;
  onViewOnMap?: Props['onViewOnMap'];
  onHistoryViewChange: (show: boolean) => void;
}) {
  const target = useAiChatStore((state) => state.context);
  const contextSource = useAiChatStore((state) => state.contextSource);
  const draft = useAiChatStore((state) => state.draft);
  const setDraft = useAiChatStore((state) => state.setDraft);
  const chat = useChatConversation(memberId);
  // D-AI-01 C2 · prototype chat-drawer.tsx:53-66: 아직 질문하지 않은 대화는 새 대상으로 바꾸고, 질문한 대화는 체크하지 않은 후보로 더한다.
  const [targets, setTargets] = useState<LinkedTarget[]>(() =>
    target ? [{ target, checked: true }] : [],
  );
  const [offered, setOffered] = useState(target);
  const [replyTo, setReplyTo] = useState<ChatJob | null>(null);
  const [view, setView] = useState<'chat' | 'history'>('chat');
  const [menuOpen, setMenuOpen] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);

  if (offered !== target) {
    setOffered(target);
    const asked = chat.jobs.length > 0 || chat.pending !== null;
    if (!asked) setTargets(target ? [{ target, checked: true }] : []);
    else if (target && !targets.some((item) => sameTarget(item.target, target)))
      setTargets([...targets, { target, checked: false }]);
  }
  const checked = targets
    .filter((item) => item.checked)
    .map((item) => item.target);
  const activeTargets = contextSource === 'header' ? [] : checked;
  const useTarget = activeTargets.length > 0;
  const locked =
    chat.load.kind !== 'ready' ||
    chat.sending ||
    chat.switching ||
    chat.active !== null ||
    chat.pending !== null;
  const sendable = isSendable(draft) && !locked;
  const length = questionLength(draft);

  // D-AI-02 · prototype chat-drawer.tsx:108-112: 새 질문·답변이 생기면 목록 끝으로 스크롤한다.
  const count = chat.jobs.length + (chat.pending ? 1 : 0);
  useEffect(() => {
    if (count > 0) end.current?.scrollIntoView?.({ block: 'nearest' });
  }, [count]);

  async function suggest(question: string) {
    if (locked || !useTarget) return;
    await chat.ask(question, contextFromTargets(checked));
  }

  function rewrite(question: string) {
    setReplyTo(null);
    setDraft(question);
    input.current?.focus();
  }

  async function submit() {
    if (!sendable) return;
    const sent = replyTo
      ? await chat.reply(replyTo, null, draft)
      : await chat.ask(draft, contextFromTargets(activeTargets));
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
    setMenuOpen(false);
    if (await chat.startNew()) {
      setReplyTo(null);
      setView('chat');
      onHistoryViewChange(false);
    }
  }

  async function open(id: string) {
    const changed = id !== chat.sessionId;
    // 열지 못하면 질문 창으로 돌아가 오류 안내를 보여 준다. 대화는 그대로다.
    const opened = await chat.open(id);
    if (opened && changed) setReplyTo(null);
    setView('chat');
    onHistoryViewChange(false);
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
      <div className="absolute top-3 right-14 z-30">
        <button
          type="button"
          className="grid size-9 place-items-center rounded-full text-panel-secondary transition-colors hover:bg-panel-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-panel-ink"
          aria-label="대화 메뉴"
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="size-5"
            fill="currentColor"
          >
            <circle cx="12" cy="5" r="1.8" />
            <circle cx="12" cy="12" r="1.8" />
            <circle cx="12" cy="19" r="1.8" />
          </svg>
        </button>
        {menuOpen && (
          <div
            role="menu"
            aria-label="대화 메뉴"
            className="absolute top-11 right-0 z-30 min-w-44 rounded-xl border border-panel-line bg-white p-1.5 shadow-lg"
          >
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-caption text-panel-ink hover:bg-panel-soft focus-visible:outline-2 focus-visible:outline-panel-ink"
              aria-pressed={view === 'history'}
              onClick={() => {
                setMenuOpen(false);
                setView('history');
                onHistoryViewChange(true);
              }}
            >
              대화 기록
            </button>
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-caption text-panel-ink hover:bg-panel-soft focus-visible:outline-2 focus-visible:outline-panel-ink disabled:cursor-not-allowed disabled:opacity-40"
              disabled={!chat.canSwitch}
              onClick={() => void startNew()}
            >
              새 대화
            </button>
          </div>
        )}
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
          onBack={() => {
            setView('chat');
            onHistoryViewChange(false);
          }}
        />
      ) : (
        <>
          <div className={`${ui.scroll} flex flex-col`}>
            {contextSource !== 'header' && (
              <section
                className={`${ui.section} shrink-0`}
                aria-labelledby="ai-chat-target"
              >
                <h3 id="ai-chat-target">질문에 연결할 대상</h3>
                {targets.length ? (
                  <ul className="flex flex-col gap-2">
                    {targets.map((item, index) => (
                      <li key={`${item.target.kind}:${item.target.id}`}>
                        <label className="flex items-start gap-2">
                          <input
                            type="checkbox"
                            checked={item.checked}
                            onChange={(event) =>
                              setTargets(
                                targets.map((other, at) =>
                                  at === index
                                    ? {
                                        ...other,
                                        checked: event.target.checked,
                                      }
                                    : other,
                                ),
                              )
                            }
                            className="peer sr-only"
                          />
                          <span
                            aria-hidden="true"
                            className="mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border border-panel-control bg-white transition-colors peer-checked:border-[5px] peer-checked:border-panel-ink peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-panel-ink"
                          />
                          <span>
                            <span className={ui.itemTitle}>
                              {targetLabel(item.target)}
                            </span>
                            <span className={`${ui.muted} block`}>
                              {TARGET_KIND[item.target.kind]}
                              {item.target.evidenceIds?.length
                                ? ` · 근거 ${item.target.evidenceIds.length}건`
                                : ''}
                            </span>
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={ui.muted}>
                    지도에서 기업이나 사건을 고르면 질문에 연결할 수 있어요.
                  </p>
                )}
              </section>
            )}

            <div aria-live="polite" className="sr-only">
              {announced ? statusText(announced) : ''}
            </div>

            {chat.load.kind === 'loading' && (
              <LoadingIndicator
                label="이전 대화를 불러오고 있어요."
                className={`${ui.state} flex min-h-12 w-full`}
              />
            )}
            {chat.load.kind === 'error' && (
              <LoadError
                error={chat.load.error}
                onRecheck={() => void chat.recheck()}
                onNew={() => void startNew()}
              />
            )}
            {chat.load.kind === 'ready' &&
              chat.jobs.length === 0 &&
              !chat.pending && (
                <section
                  className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-10 text-center"
                  aria-label="새 대화 시작"
                >
                  <span className="grid size-12 place-items-center rounded-full bg-zoop-soft text-zoop-ink">
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 24 24"
                      fill="none"
                      className="size-6"
                    >
                      <path
                        d="M12 2.75 14.2 9.8 21.25 12l-7.05 2.2L12 21.25 9.8 14.2 2.75 12 9.8 9.8 12 2.75Z"
                        stroke="currentColor"
                        strokeLinejoin="round"
                        strokeWidth="1.6"
                      />
                      <path
                        d="m19 2 .7 2.3L22 5l-2.3.7L19 8l-.7-2.3L16 5l2.3-.7L19 2Z"
                        fill="currentColor"
                      />
                    </svg>
                  </span>
                  <h3 className="m-0 text-title-sm font-semibold leading-snug text-panel-ink">
                    무엇을 함께 살펴볼까요?
                  </h3>
                </section>
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
                onRewrite={rewrite}
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
            <div ref={end} aria-hidden="true" />
          </div>

          {chat.load.kind === 'ready' &&
            chat.jobs.length === 0 &&
            !chat.pending && (
              <section className="shrink-0 px-4 pt-3" aria-label="추천 질문">
                <ul className="m-0 flex list-none flex-col items-start gap-2 p-0">
                  {SUGGESTIONS.map((question) => (
                    <li key={question}>
                      <button
                        type="button"
                        className="inline-flex max-w-full items-center gap-2 rounded-full bg-panel-soft px-4 py-2.5 text-left text-caption leading-relaxed text-panel-ink transition-colors hover:bg-zoop-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-panel-ink disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={locked || !useTarget}
                        onClick={() => void suggest(question)}
                      >
                        {question}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

          <form
            className="shrink-0 px-4 pt-3 pb-4"
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
            <div className="rounded-2xl border border-panel-line bg-white p-3 transition-colors focus-within:border-panel-control">
              <label className="sr-only" htmlFor="ai-chat-input">
                질문
              </label>
              <textarea
                id="ai-chat-input"
                ref={input}
                rows={2}
                className="min-h-12 w-full resize-none border-0 bg-transparent px-1 py-1 text-caption leading-[18px] focus:outline-none"
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
              <div className="flex items-center justify-end pt-2">
                <button
                  type="submit"
                  className={ui.button}
                  disabled={!sendable}
                  aria-busy={chat.sending}
                >
                  {chat.sending ? '보내는 중' : '보내기'}
                </button>
              </div>
            </div>
            <div id="ai-chat-hint" className={`${ui.muted} mt-1`}>
              {length > MAX_QUESTION - 500 && (
                <p
                  className={
                    length > MAX_QUESTION ? 'm-0 text-zoop-alert' : 'm-0'
                  }
                >
                  {length}/{MAX_QUESTION}자
                </p>
              )}
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
