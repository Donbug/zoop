// AI 질문 창(UI-10, FS045–FS053).
// 대화·질문 작업·답변은 서버가 저장한다. 이 창은 닫아도 대화와 처리 중인 작업이 그대로 남고(창은 앱 셸 안에서 계속 살아 있다),
// 다시 열면 서버에서 가장 최근 대화를 찾아 완료된 답변을 그대로 보여 주고 처리 중이면 상태를 이어서 확인한다.
// 지도·기업 상세에서 연 질문은 선택 대상을 '질문에 연결할 대상'으로 보여 주고, 확인·해제한 대상만 질문에 실어 보낸다.
// 이미 질문한 대화에서는 화면에서 새로 전달받은 대상을 자동으로 덮어쓰지 않는다(체크하지 않은 후보로만 더한다).
import { Building2, Link2, LogIn, MessageCircleQuestion, MessageSquarePlus, Send, Sparkles, Zap, type LucideIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useLogout, useSession, type ChatJob } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/dialog";
import { EmptyState, ErrorState, SkeletonLines, describeError } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { ChatJobItem, PendingItem, type JobActions } from "./chat-job-view";
import { useChat } from "./use-chat";

/** 질문에 연결할 수 있는 지도 대상(BFF 맥락 id: 기업·사건·연결선). */
export interface ChatTarget {
  id: string;
  kind: "company" | "issue" | "edge";
  label: string;
  /** 적용 기간·근거 수 요약(데이터에 있는 값만) */
  detail?: string;
  /** 처음부터 체크해 둘지(기본 true). 연결선의 양 끝 기업처럼 범위를 넓히는 대상은 꺼 둔다. */
  checked?: boolean;
  /** 이 대상에서 질문에 쓸 근거 id를 이미 알면 함께 전달한다(서버 작업에 근거 참조로 고정된다). 체크한 대상이 모두 줄 때만 보낸다. */
  evidenceIds?: string[];
}

const MAX_EVIDENCE_REFS = 50;

export interface ChatContext {
  targets: ChatTarget[];
}

const targetIcon: Record<ChatTarget["kind"], LucideIcon> = { company: Building2, issue: Zap, edge: Link2 };

// 세 번째 질문은 예측을 묻는 질문이다. 서버는 이런 질문에 답을 지어내지 않고 '보류'로 응답한다(보류 상태 확인용).
const suggestions = ["함께 언급된 기업은 어디인가요?", "이 사건은 언제, 어떤 보도로 알려졌나요?", "이 사건 이후 주가 전망은 어떤가요?"];

interface Selection {
  targets: ChatTarget[];
  checked: ReadonlySet<string>;
}

const selectionOf = (targets: ChatTarget[]): Selection => ({
  targets,
  checked: new Set(targets.filter((t) => t.checked !== false).map((t) => t.id)),
});

/** 서버에 저장된 마지막 질문의 대상을 다시 고른 상태로 만든다(화면을 옮기거나 새로고침해도 이어지는 대화의 대상). */
function selectionOfJob(job: ChatJob): Selection {
  const targets = job.context.items
    .filter((item): item is typeof item & { kind: ChatTarget["kind"] } => item.kind !== "evidence")
    .map((item) => ({ id: item.id, kind: item.kind, label: item.label }));
  return selectionOf(targets);
}

/** 화면이 새로 전달한 대상: 아직 질문하지 않은 대화는 그 대상으로 바꾸고, 이미 질문한 대화는 후보로만 더한다. */
function offered(prev: Selection, targets: ChatTarget[], fresh: boolean): Selection {
  if (fresh) return selectionOf(targets);
  const known = new Set(prev.targets.map((t) => t.id));
  return { targets: [...prev.targets, ...targets.filter((t) => !known.has(t.id)).map((t) => ({ ...t, checked: false }))], checked: prev.checked };
}

interface ChatDrawerProps {
  context: ChatContext;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onShowEvidence: (title: string, evidenceIds: string[]) => void;
}

export function ChatDrawer({ context, open, onOpenChange, onShowEvidence }: ChatDrawerProps) {
  const session = useSession();
  const kind = session.data?.kind;
  const member = kind === "member";
  const chat = useChat({ member, open });
  const navigate = useNavigate();
  const logout = useLogout();
  const [question, setQuestion] = useState("");
  const [selection, setSelection] = useState<Selection>(() => selectionOf(context.targets));
  const listId = useId();
  const endRef = useRef<HTMLLIElement>(null);

  const empty = chat.jobs.length === 0 && !chat.pending;
  const linked = selection.targets.filter((t) => selection.checked.has(t.id));
  const linkedIds = linked.map((t) => t.id);
  const linkedLabels = linked.map((t) => t.label.replace(/\.$/, ""));

  // 화면에서 창을 다시 열 때마다 새로 전달된 대상을 반영한다.
  const [seenContext, setSeenContext] = useState(context);
  if (seenContext !== context) {
    setSeenContext(context);
    setSelection((prev) => offered(prev, context.targets, empty));
  }

  // 서버의 기존 대화를 찾았으면 그 대화의 마지막 질문 대상으로 이어 간다. 지금 화면의 대상은 체크하지 않은 후보로 남긴다.
  const latest = useRef({ jobs: chat.jobs, context });
  latest.current = { jobs: chat.jobs, context };
  useEffect(() => {
    const last = latest.current.jobs.at(-1);
    if (!chat.sessionId || !last) return;
    setSelection(offered(selectionOfJob(last), latest.current.context.targets, false));
  }, [chat.sessionId]);

  // 새 질문·답변이 생기면 끝으로 스크롤한다.
  const count = chat.jobs.length + (chat.pending ? 1 : 0);
  useEffect(() => {
    if (open && count > 0) endRef.current?.scrollIntoView({ block: "nearest" });
  }, [open, count]);

  const canType = member && chat.ready;
  const blockedByActive = chat.hasActive;
  const canSend = canType && !blockedByActive && question.trim().length > 0;

  const evidenceRefs = linked.length > 0 && linked.every((t) => t.evidenceIds) ? [...new Set(linked.flatMap((t) => t.evidenceIds ?? []))] : [];
  const ask = async (
    text: string,
    context: { contextIds: string[]; evidenceIds?: string[] } = { contextIds: linkedIds, evidenceIds: evidenceRefs.length <= MAX_EVIDENCE_REFS ? evidenceRefs : [] },
    labels: string[] = linkedLabels,
  ) => {
    const trimmed = text.trim();
    if (!trimmed || !canType || blockedByActive) return false;
    return chat.send(trimmed, context, labels);
  };
  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (await ask(question)) setQuestion("");
  };
  const toggle = (id: string) =>
    setSelection((prev) => {
      const checked = new Set(prev.checked);
      if (!checked.delete(id)) checked.add(id);
      return { ...prev, checked };
    });

  const startNew = async () => {
    if (await chat.startNew()) setSelection(selectionOf(context.targets));
  };
  const goLogin = () =>
    logout.mutate(undefined, {
      onSettled: () => {
        onOpenChange(false);
        navigate("/login");
      },
    });

  const actions: JobActions = {
    retry: (jobId) => void chat.retryJob(jobId),
    cancel: (jobId) => void chat.cancelJob(jobId),
    choose: (job, choice) => {
      setSelection((prev) => ({
        targets: prev.targets.some((t) => t.id === choice.id) ? prev.targets : [...prev.targets, { id: choice.id, kind: "company", label: choice.label }],
        checked: new Set([choice.id]),
      }));
      void ask(job.question, { contextIds: [choice.id] }, [choice.label]);
    },
    rewrite: setQuestion,
    showEvidence: onShowEvidence,
    leave: () => onOpenChange(false),
  };

  const noticeText = chat.notice && describeError(chat.notice.error).message;

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="AI에게 묻기"
      description={member ? `질문 대상: ${linkedLabels.length > 0 ? linkedLabels.join(" · ") : "없음"}` : "로그인한 회원만 질문할 수 있어요"}
      closeLabel="AI 질문 창 닫기"
      headerExtra={
        member && (
          <div>
            <Button variant="ghost" size="sm" className="-ml-3" onClick={() => void startNew()} disabled={empty || chat.startingNew || !chat.ready} loading={chat.startingNew}>
              <MessageSquarePlus aria-hidden="true" />
              새 대화
            </Button>
          </div>
        )
      }
      footer={
        <div className="flex flex-col gap-2">
          {member && (
            <form onSubmit={(event) => void onSubmit(event)} className="flex items-end gap-2">
              <Input
                label="질문"
                hideLabel
                className="flex-1"
                placeholder={chat.ready ? "질문을 입력해 주세요" : "대화를 확인하고 있어요"}
                value={question}
                maxLength={1000}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={!chat.ready}
                aria-describedby={`${listId}-status`}
              />
              <Button type="submit" loading={chat.pending?.phase === "sending"} disabled={!canSend}>
                <Send aria-hidden="true" />
                보내기
              </Button>
            </form>
          )}
          <div id={`${listId}-status`} role="status" className="flex flex-col gap-1 text-sm">
            {member && blockedByActive && (
              <p className="text-text-secondary">
                {chat.pending
                  ? "먼저 보낸 질문이 접수됐는지 확인하는 중이라 새 질문은 보낼 수 없어요. 쓰던 질문은 그대로 남아 있어요."
                  : "답변을 준비하는 중이라 새 질문은 끝난 뒤에 보낼 수 있어요. 쓰던 질문은 그대로 남아 있어요."}
              </p>
            )}
            {noticeText && <p className="font-medium text-warning">{noticeText}</p>}
            {member && linkedIds.length === 0 && chat.ready && !blockedByActive && (
              <p className="text-text-secondary">연결한 대상이 없어요. 질문에 기업 이름을 적거나 위에서 대상을 골라 주세요.</p>
            )}
            {newErrorText(chat.newError)}
          </div>
          {member && (
            <p className="flex items-center gap-1.5 text-sm text-text-secondary">
              <Sparkles className="size-4 shrink-0" aria-hidden="true" />
              AI가 생성한 예시 답변이며 투자 권유가 아니에요.
            </p>
          )}
        </div>
      }
    >
      {!member ? (
        <EmptyState
          className="px-0 py-4"
          title={kind === "guest" ? "AI 질문은 로그인한 뒤에 쓸 수 있어요" : "AI 질문을 쓰려면 로그인해 주세요"}
          description="회원은 지도에서 고른 대상과 함께 바로 AI에게 물어볼 수 있어요. 비회원은 질문을 보낼 수 없어요."
          action={
            <Button onClick={goLogin} loading={logout.isPending}>
              <LogIn aria-hidden="true" />
              로그인하기
            </Button>
          }
        />
      ) : (
        <div className="-mx-4 flex flex-col md:-mx-5">
          {selection.targets.length > 0 && (
            <section aria-labelledby={`${listId}-title`} className="pb-2">
              <SectionHeader id={`${listId}-title`} as="h3" icon={Link2} title="질문에 연결할 대상" className="pt-0" />
              <ul className="flex flex-col">
                {selection.targets.map((target) => {
                  const Icon = targetIcon[target.kind];
                  const inputId = `${listId}-${target.id}`;
                  return (
                    <li key={target.id}>
                      <label htmlFor={inputId} className="flex min-h-11 cursor-pointer items-start gap-3 px-4 py-2 hover:bg-surface-sunken md:px-5">
                        <input
                          id={inputId}
                          type="checkbox"
                          checked={selection.checked.has(target.id)}
                          onChange={() => toggle(target.id)}
                          className="mt-0.5 size-5 shrink-0 accent-(--color-brand-primary)"
                        />
                        <Icon className="mt-0.5 size-5 shrink-0 text-text-secondary" aria-hidden="true" />
                        <span className="flex min-w-0 flex-col">
                          <span className="text-base text-text-primary">{target.label}</span>
                          {target.detail && <span className="text-sm text-text-secondary tabular-nums">{target.detail}</span>}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {chat.current.isPending && chat.sessionId === null && (
            <div className="px-4 md:px-5">
              <SkeletonLines lines={2} label="이전 대화를 확인하고 있어요" />
            </div>
          )}
          {chat.current.isError && chat.sessionId === null && (
            <ErrorState
              className="px-4 md:px-5"
              error={chat.current.error}
              title="이전 대화를 확인하지 못했어요"
              message="대화가 없는 것이 아니라 확인에 실패했어요. 다시 확인하면 이어서 질문할 수 있어요."
              onRetry={() => void chat.current.refetch()}
              compact
            />
          )}
          {chat.conversation.isError && (
            <div role="status" className="flex flex-wrap items-center gap-2 px-4 pb-2 text-sm text-text-secondary md:px-5">
              <span>답변 상태를 확인하지 못했어요. 처리가 취소된 것은 아니에요.</span>
              <Button variant="secondary" size="sm" onClick={() => void chat.conversation.refetch()}>
                다시 확인
              </Button>
            </div>
          )}

          {chat.ready && empty && (
            <section aria-labelledby="chat-suggestions">
              <SectionHeader id="chat-suggestions" as="h3" icon={MessageCircleQuestion} title="추천 질문" className="pt-0" />
              <ul>
                {suggestions.map((s) => (
                  <li key={s}>
                    <ListRow leading={<MessageCircleQuestion />} title={s} onClick={() => void ask(s)} disabled={linkedIds.length === 0} />
                  </li>
                ))}
              </ul>
            </section>
          )}

          <ol className="flex flex-col divide-y divide-border-subtle" aria-live="polite">
            {chat.jobs.map((job) => (
              <li key={job.id} className="flex flex-col gap-3 px-4 py-4 first:pt-0 md:px-5">
                <ChatJobItem job={job} actions={actions} />
              </li>
            ))}
            {chat.pending && (
              <li className="flex flex-col gap-3 px-4 py-4 first:pt-0 md:px-5">
                <PendingItem pending={chat.pending} onRecheck={() => void chat.recheck()} />
              </li>
            )}
            <li ref={endRef} aria-hidden="true" />
          </ol>
        </div>
      )}
    </Sheet>
  );
}

function newErrorText(error: unknown) {
  if (!error) return null;
  return <p className="font-medium text-warning">새 대화를 만들지 못했어요. 지금 대화는 그대로예요. {describeError(error).message}</p>;
}
