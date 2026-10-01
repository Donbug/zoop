// AI 질문 창(UI-10). 대화는 이 창 안에서만 유지되고 새로고침하면 사라진다(D-12).
// AI 생성 표시는 입력창 아래 아이콘 + 한 줄 고지로 한 번, 답변 앞에는 스크린리더용 이름이 붙은 AI 아이콘을 둔다.
// 지도에서 연 질문(요구 25)은 선택 대상과 그 기간·근거 수를 '질문에 연결할 대상'으로 보여준다. 사용자가 대상을 확인하고
// 해제할 수 있고, 질문은 체크된 대상(contextIds)에만 연결해 보낸다. 대상을 모두 해제하면 보낼 수 없다.
import { Building2, ExternalLink, Link2, MessageCircleQuestion, Send, ShieldQuestion, Sparkles, Zap, type LucideIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import type { Schemas } from "@/api/client";
import { useAskQuestion, useCreateChatSession } from "@/api/queries";
import { FeedbackButtons } from "@/components/domain/feedback-buttons";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/dialog";
import { ErrorState, SkeletonLines } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { errorReasonMessage } from "@/lib/labels";

/** 질문에 연결할 수 있는 지도 대상(BFF 맥락 id: 기업·사건·연결선). */
export interface ChatTarget {
  id: string;
  kind: "company" | "issue" | "edge";
  label: string;
  /** 적용 기간·근거 수 요약(데이터에 있는 값만) */
  detail?: string;
  /** 처음부터 체크해 둘지(기본 true). 연결선의 양 끝 기업처럼 범위를 넓히는 대상은 꺼 둔다. */
  checked?: boolean;
}

export interface ChatContext {
  targets: ChatTarget[];
}

const targetIcon: Record<ChatTarget["kind"], LucideIcon> = { company: Building2, issue: Zap, edge: Link2 };

interface Exchange {
  id: number;
  question: string;
  /** 이 질문을 보낼 때 연결해 둔 대상 이름 */
  labels: string[];
  answer?: Schemas["ChatMessageResponse"];
  error?: unknown;
}

// 세 번째 질문은 예측을 묻는 질문이다. 서버는 이런 질문에 답을 지어내지 않고 '보류'로 응답한다(보류 상태 확인용).
const suggestions = ["함께 언급된 기업은 어디인가요?", "이 사건은 언제, 어떤 보도로 알려졌나요?", "이 사건 이후 주가 전망은 어떤가요?"];

export function ChatDrawer({ context, open, onOpenChange }: { context: ChatContext; open: boolean; onOpenChange: (open: boolean) => void }) {
  const createSession = useCreateChatSession();
  const ask = useAskQuestion();
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [checked, setChecked] = useState<ReadonlySet<string>>(() => new Set(context.targets.filter((t) => t.checked !== false).map((t) => t.id)));
  const sessionId = createSession.data?.id;
  const contextIds = context.targets.map((t) => t.id);
  const linkedIds = contextIds.filter((id) => checked.has(id));
  const linkedLabels = context.targets.filter((t) => checked.has(t.id)).map((t) => t.label.replace(/\.$/, ""));
  const listId = useId();

  // 창이 처음 열릴 때 맥락을 담은 세션을 한 번만 만든다.
  const started = useRef(false);
  const { mutate: startSession } = createSession;
  useEffect(() => {
    if (!open || started.current) return;
    started.current = true;
    startSession(contextIds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, startSession]);

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !sessionId || ask.isPending || linkedIds.length === 0) return;
    const id = Date.now();
    setExchanges((prev) => [...prev, { id, question: trimmed, labels: linkedLabels }]);
    setQuestion("");
    ask.mutate(
      { sessionId, question: trimmed, contextIds: linkedIds },
      {
        onSuccess: (answer) => setExchanges((prev) => prev.map((x) => (x.id === id ? { ...x, answer } : x))),
        onError: (error) => setExchanges((prev) => prev.map((x) => (x.id === id ? { ...x, error } : x))),
      },
    );
  };
  const toggle = (id: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    send(question);
  };

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="AI에게 묻기"
      description={`질문 대상: ${linkedLabels.length > 0 ? linkedLabels.join(" · ") : "없음"}`}
      closeLabel="AI 질문 창 닫기"
      footer={
        <div className="flex flex-col gap-2">
          <form onSubmit={onSubmit} className="flex items-end gap-2">
            <Input
              label="질문"
              hideLabel
              className="flex-1"
              placeholder={sessionId ? "질문을 입력해 주세요" : "질문 창을 준비하고 있어요"}
              value={question}
              maxLength={1000}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={!sessionId}
            />
            <Button type="submit" loading={ask.isPending} disabled={!sessionId || question.trim().length === 0 || linkedIds.length === 0}>
              <Send aria-hidden="true" />
              보내기
            </Button>
          </form>
          {linkedIds.length === 0 && (
            <p role="status" className="text-sm font-medium text-warning">
              질문에 연결할 대상을 하나 이상 골라 주세요.
            </p>
          )}
          <p className="flex items-center gap-1.5 text-sm text-text-secondary">
            <Sparkles className="size-4 shrink-0" aria-hidden="true" />
            AI가 생성한 예시 답변이며 투자 권유가 아니에요.
          </p>
        </div>
      }
    >
      <div className="-mx-4 flex flex-col md:-mx-5">
        <section aria-labelledby={`${listId}-title`} className="pb-2">
          <SectionHeader id={`${listId}-title`} as="h3" icon={Link2} title="질문에 연결할 대상" className="pt-0" />
          <ul className="flex flex-col">
            {context.targets.map((target) => {
              const Icon = targetIcon[target.kind];
              const inputId = `${listId}-${target.id}`;
              return (
                <li key={target.id}>
                  <label htmlFor={inputId} className="flex min-h-11 cursor-pointer items-start gap-3 px-4 py-2 hover:bg-surface-sunken md:px-5">
                    <input
                      id={inputId}
                      type="checkbox"
                      checked={checked.has(target.id)}
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
        {createSession.isPending && (
          <div className="px-4 md:px-5">
            <SkeletonLines lines={2} label="질문 창을 준비하고 있어요" />
          </div>
        )}
        {createSession.isError && (
          <ErrorState
            className="px-4 md:px-5"
            error={createSession.error}
            title="질문 창을 준비하지 못했어요"
            onRetry={() => createSession.mutate(contextIds)}
          />
        )}

        {sessionId && exchanges.length === 0 && (
          <section aria-labelledby="chat-suggestions">
            <SectionHeader id="chat-suggestions" as="h3" icon={MessageCircleQuestion} title="추천 질문" className="pt-0" />
            <ul>
              {suggestions.map((s) => (
                <li key={s}>
                  <ListRow leading={<MessageCircleQuestion />} title={s} onClick={() => send(s)} disabled={linkedIds.length === 0} />
                </li>
              ))}
            </ul>
          </section>
        )}

        <ol className="flex flex-col divide-y divide-border-subtle" aria-live="polite">
          {exchanges.map((x) => (
            <li key={x.id} className="flex flex-col gap-3 px-4 py-4 first:pt-0 md:px-5">
              <p className="text-base font-semibold text-text-primary">
                <span className="sr-only">내 질문: </span>
                {x.question}
              </p>
              <p className="-mt-2 text-sm text-text-secondary">연결한 대상: {x.labels.join(" · ")}</p>
              {!x.answer && !x.error && <SkeletonLines lines={3} label="답변을 준비하고 있어요" />}
              {x.error !== undefined && <ErrorState error={x.error} title="답변을 받지 못했어요" onRetry={() => send(x.question)} compact />}
              {x.answer && <Answer answer={x.answer} />}
              {x.answer && <FeedbackButtons feature="chatbot_answer" targetId={x.answer.messageId} subject="이 답변" />}
            </li>
          ))}
        </ol>
      </div>
    </Sheet>
  );
}

function Answer({ answer }: { answer: Schemas["ChatMessageResponse"] }) {
  if (answer.status === "insufficient_evidence") {
    const reason = errorReasonMessage(answer.reason);
    return (
      <div className="flex flex-col gap-1 text-base text-text-secondary">
        <p className="flex items-start gap-1.5 text-text-primary">
          <ShieldQuestion className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          수집된 기사에서 근거를 찾지 못해 답변을 보류했어요.
        </p>
        {reason && <p className="text-sm">{reason}</p>}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-start gap-2 text-base leading-relaxed whitespace-pre-line text-text-primary">
        <Sparkles className="mt-1 size-4 shrink-0 text-text-secondary" role="img" aria-label="AI 예시 답변" />
        <span>{answer.answer}</span>
      </p>
      {answer.citations.length > 0 && (
        <section className="flex flex-col gap-2" aria-label={`근거 문서 ${answer.citations.length}건`}>
          <p className="text-sm font-semibold text-text-secondary">근거 문서 {answer.citations.length}건</p>
          <ul className="flex flex-col gap-2">
            {answer.citations.map((c) => (
              <li key={c.evidenceId} className="flex flex-col gap-1 bg-surface-sunken px-4 py-3">
                <p className="text-sm text-text-secondary">
                  {c.publisher ?? "출처 미상"}
                  {c.articleTitle ? ` · ${c.articleTitle}` : ""}
                </p>
                <p className="text-base text-text-primary">“{c.quote}”</p>
                {c.url && (
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex min-h-11 w-fit items-center gap-1 text-sm font-medium text-brand-primary underline-offset-4 hover:underline"
                  >
                    원문 보기 <ExternalLink className="size-3.5" aria-hidden="true" />
                    <span className="sr-only">(새 창에서 열림)</span>
                  </a>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
