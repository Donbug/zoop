// AI 질문 한 건(작업)이 어떻게 보이는지: 처리 중 · 완료(답변 / 되묻기 / 조건 안내 / 근거 부족) · 실패 · 취소 · 아직 접수 여부를 모르는 전송.
// 화면에 보이는 답변은 서버가 검증하고 저장한 결과뿐이다. 실제 적용한 기업·사건·기간은 답변마다 함께 보인다.
import {
  Building2,
  CalendarRange,
  CircleAlert,
  ExternalLink,
  FileText,
  Info,
  ListChecks,
  Map as MapIcon,
  MessageCircleQuestion,
  RotateCw,
  ShieldQuestion,
  Sparkles,
  Zap,
} from "lucide-react";
import { Link } from "react-router";
import type { Schemas } from "@/api/client";
import { type ChatJob } from "@/api/queries";
import { FeedbackButtons } from "@/components/domain/feedback-buttons";
import { Button } from "@/components/ui/button";
import { SkeletonLines } from "@/components/ui/feedback";
import type { PendingSend } from "./use-chat";

type ChatResult = Schemas["ChatResult"];
type Applied = Schemas["ChatApplied"];

export interface JobActions {
  retry: (jobId: string) => void;
  cancel: (jobId: string) => void;
  /** 되묻기에서 고른 기업으로 같은 질문을 새 작업으로 다시 보낸다 */
  choose: (job: ChatJob, choice: { id: string; label: string }) => void;
  /** 고쳐서 새 질문으로 보내도록 질문을 입력칸으로 되돌린다 */
  rewrite: (question: string) => void;
  showEvidence: (title: string, evidenceIds: string[]) => void;
  /** 다른 화면으로 이동하기 전에 창을 닫는다(대화와 작업은 그대로 남는다) */
  leave: () => void;
}

const failureTitle: Record<string, string> = {
  validation_failed: "답변을 검증하지 못했어요",
  save_failed: "답변을 저장하지 못했어요",
  result_lost: "검증한 답변을 보관하지 못했어요",
  transient: "일시적인 문제로 답변하지 못했어요",
  permission_denied: "질문을 처리할 권한을 확인하지 못했어요",
  internal: "답변을 만들지 못했어요",
};

/** 답변 본문의 맺음 고지는 입력창 아래 고지와 겹치므로 뺀다. */
function withoutDisclaimer(text: string) {
  return text.replace(/\n?인용한 문장은 원인이나 투자 판단을 뜻하지 않아요\.$/, "");
}

/** 인용을 따로 목록으로 보여 주므로, 규칙 기반 답변 본문에서 같은 인용 줄("1. “…”")은 뺀다. */
function withoutQuoteLines(text: string) {
  return text
    .split("\n")
    .filter((line) => !/^\d+\. [“"]/.test(line))
    .join("\n")
    .trim();
}

function dayRange(start: string, end: string) {
  return start === end ? start : `${start} ~ ${end}`;
}

function AppliedScope({ applied }: { applied: Applied }) {
  const names = applied.companies.map((c) => c.label);
  const shownNames = names.slice(0, 3).join(" · ") + (names.length > 3 ? ` 외 ${names.length - 3}곳` : "");
  const period = applied.period;
  const periodText = period
    ? period.basis === "evidence"
      ? `인용 근거 발행 ${dayRange(period.start, period.end)}`
      : `${dayRange(period.start, period.end)}${period.expression ? ` (${period.expression})` : ""}`
    : "기간 지정 없음";
  return (
    <section aria-label="적용한 조건" className="flex flex-col gap-1 text-sm text-text-secondary">
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {names.length > 0 && (
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <Building2 className="size-4 shrink-0" aria-hidden="true" />
            <span className="sr-only">적용 기업: </span>
            {shownNames}
          </span>
        )}
        {applied.issues.length > 0 && (
          <span className="inline-flex items-center gap-1.5 tabular-nums">
            <Zap className="size-4 shrink-0" aria-hidden="true" />
            <span className="sr-only">적용 사건: </span>
            {applied.issues.length}건
          </span>
        )}
        <span className="inline-flex items-center gap-1.5 tabular-nums">
          <CalendarRange className="size-4 shrink-0" aria-hidden="true" />
          <span className="sr-only">적용 기간: </span>
          {periodText}
        </span>
      </p>
      {applied.questionOverrodeContext && (
        <p className="flex items-start gap-1.5">
          <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          질문에 적은 대상을 먼저 적용했어요.
        </p>
      )}
    </section>
  );
}

function graphUrl(target: Schemas["GraphTarget"]) {
  return `/?mode=all&select=${target.kind === "edge" ? "edge" : "node"}:${encodeURIComponent(target.id)}`;
}

function targetLabel(target: Schemas["GraphTarget"], applied: Applied) {
  if (target.kind === "company") return applied.companies.find((c) => c.id === target.id)?.label ?? "기업";
  if (target.kind === "issue") return applied.issues.find((i) => i.id === target.id)?.label ?? "사건";
  return "연결 관계";
}

/** 서버가 그래프에 실제로 있다고 확인한 대상만 온다. 답변 문장으로 새 연결을 만들지 않고 지도에서 그 대상을 고른 상태로 연다. */
function GraphLinks({ result, onLeave }: { result: ChatResult; onLeave: () => void }) {
  if (result.graphTargets.length === 0) return null;
  return (
    <section aria-label="지도에서 보기" className="flex flex-wrap gap-2">
      {result.graphTargets.slice(0, 4).map((target) => {
        const label = targetLabel(target, result.applied);
        return (
          <Button key={`${target.kind}:${target.id}`} variant="secondary" size="sm" asChild className="max-w-full">
            <Link to={graphUrl(target)} onClick={onLeave}>
              <MapIcon aria-hidden="true" />
              <span className="truncate">{label.length > 22 ? `${label.slice(0, 21)}…` : label}</span>
              <span className="sr-only"> 지도에서 보기</span>
            </Link>
          </Button>
        );
      })}
    </section>
  );
}

function Citations({ result }: { result: ChatResult }) {
  if (result.citations.length === 0) return null;
  return (
    <section className="flex flex-col gap-2" aria-label={`근거 문서 ${result.citations.length}건`}>
      <p className="text-sm font-semibold text-text-secondary">근거 문서 {result.citations.length}건</p>
      <ul className="flex flex-col gap-2">
        {result.citations.map((c) => (
          <li key={c.evidenceId} className="flex flex-col gap-1 bg-surface-sunken px-4 py-3">
            <p className="text-sm text-text-secondary">
              {c.publisher ?? "출처 미상"}
              {c.articleTitle ? ` · ${c.articleTitle}` : ""}
              {c.publishedAt ? <span className="tabular-nums"> · {c.publishedAt.slice(0, 10)}</span> : null}
            </p>
            <p className="text-base text-text-primary">“{c.quote}”</p>
            {c.url ? (
              <a
                href={c.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-11 w-fit items-center gap-1 text-sm font-medium text-brand-primary underline-offset-4 hover:underline"
              >
                원문 보기 <ExternalLink className="size-3.5" aria-hidden="true" />
                <span className="sr-only">(새 창에서 열림)</span>
              </a>
            ) : (
              <p className="text-sm text-text-tertiary">원문 링크가 없는 자료예요.</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ResultView({ job, result, actions }: { job: ChatJob; result: ChatResult; actions: JobActions }) {
  const text = withoutDisclaimer(result.answer);
  if (result.outcome === "clarification") {
    return (
      <div className="flex flex-col gap-3">
        <p className="flex items-start gap-2 text-base text-text-primary">
          <MessageCircleQuestion className="mt-0.5 size-5 shrink-0 text-text-secondary" aria-hidden="true" />
          <span>{text}</span>
        </p>
        {result.choices.length > 0 && (
          <ul className="flex flex-wrap gap-2" aria-label="고를 수 있는 기업">
            {result.choices.map((choice) => (
              <li key={choice.id}>
                <Button variant="secondary" size="sm" onClick={() => actions.choose(job, choice)}>
                  {choice.label}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  if (result.outcome === "guidance") {
    return (
      <div className="flex flex-col gap-3">
        <p className="flex items-start gap-2 text-base text-text-primary">
          <ListChecks className="mt-0.5 size-5 shrink-0 text-text-secondary" aria-hidden="true" />
          <span>{text}</span>
        </p>
        {result.action?.kind === "set_watchlist" && (
          <div>
            <Button variant="secondary" size="sm" asChild>
              <Link to="/me/stocks" onClick={actions.leave}>
                {result.action.label}
              </Link>
            </Button>
          </div>
        )}
      </div>
    );
  }
  if (result.outcome === "insufficient_evidence") {
    return (
      <div className="flex flex-col gap-2">
        <p className="flex items-start gap-2 text-base text-text-primary">
          <ShieldQuestion className="mt-0.5 size-5 shrink-0 text-text-secondary" aria-hidden="true" />
          <span className="whitespace-pre-line">{text}</span>
        </p>
        <AppliedScope applied={result.applied} />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-start gap-2 text-base leading-relaxed whitespace-pre-line text-text-primary">
        <Sparkles className="mt-1 size-4 shrink-0 text-text-secondary" role="img" aria-label="AI 예시 답변" />
        <span>{result.citations.length > 0 ? withoutQuoteLines(text) : text}</span>
      </p>
      <AppliedScope applied={result.applied} />
      <Citations result={result} />
      <div className="flex flex-wrap items-center gap-2">
        {result.sources.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => actions.showEvidence(job.question, result.sources)}>
            <FileText aria-hidden="true" />
            근거 문서 열기
          </Button>
        )}
      </div>
      <GraphLinks result={result} onLeave={actions.leave} />
    </div>
  );
}

function FailureView({ job, actions }: { job: ChatJob; actions: JobActions }) {
  const failure = job.failure;
  if (!failure) return null;
  return (
    <div role="alert" className="flex flex-col items-start gap-2">
      <p className="flex items-center gap-2 text-base font-semibold text-text-primary">
        <CircleAlert className="size-5 shrink-0 text-error" aria-hidden="true" />
        {failureTitle[failure.kind] ?? "답변하지 못했어요"}
      </p>
      <p className="max-w-prose text-base text-text-secondary">{failure.message}</p>
      <div className="flex flex-wrap gap-2">
        {failure.retry === "rerun" && (
          <Button variant="secondary" size="sm" onClick={() => actions.retry(job.id)}>
            <RotateCw aria-hidden="true" />
            같은 조건으로 다시 시도
          </Button>
        )}
        {failure.retry === "save_only" && (
          <Button variant="secondary" size="sm" onClick={() => actions.retry(job.id)}>
            <RotateCw aria-hidden="true" />
            저장만 다시 시도
          </Button>
        )}
        {failure.retry === null && (
          <Button variant="secondary" size="sm" onClick={() => actions.rewrite(job.question)}>
            질문 고쳐서 새로 보내기
          </Button>
        )}
      </div>
    </div>
  );
}

export function ChatJobItem({ job, actions }: { job: ChatJob; actions: JobActions }) {
  const labels = job.context.items.map((item) => item.label.replace(/\.$/, ""));
  return (
    <>
      <p className="text-base font-semibold text-text-primary">
        <span className="sr-only">내 질문: </span>
        {job.question}
      </p>
      <p className="-mt-2 text-sm text-text-secondary tabular-nums">
        연결한 대상: {labels.length > 0 ? labels.join(" · ") : "없음"}
        {job.context.evidenceCount > 0 && ` · 근거 ${job.context.evidenceCount}건`}
        {job.context.period && ` · ${dayRange(job.context.period.start, job.context.period.end)}`}
      </p>
      {(job.status === "queued" || job.status === "running") && (
        <div className="flex flex-col items-start gap-2">
          <SkeletonLines lines={3} label="답변을 준비하고 있어요" />
          <Button variant="ghost" size="sm" onClick={() => actions.cancel(job.id)}>
            질문 취소
          </Button>
        </div>
      )}
      {job.status === "completed" && job.result && (
        <>
          <ResultView job={job} result={job.result} actions={actions} />
          <FeedbackButtons feature="chatbot_answer" targetId={job.result.messageId} subject="이 답변" />
        </>
      )}
      {job.status === "failed" && <FailureView job={job} actions={actions} />}
      {job.status === "cancelled" && (
        <div className="flex flex-col items-start gap-2">
          <p className="text-base text-text-secondary">질문을 취소했어요.</p>
          <Button variant="secondary" size="sm" onClick={() => actions.rewrite(job.question)}>
            질문 다시 쓰기
          </Button>
        </div>
      )}
    </>
  );
}

/** 서버가 접수했는지 아직 모르는 전송. 새 질문으로 바꿔 보내지 않고 같은 질문의 접수 상태만 확인한다. */
export function PendingItem({ pending, onRecheck }: { pending: PendingSend; onRecheck: () => void }) {
  return (
    <>
      <p className="text-base font-semibold text-text-primary">
        <span className="sr-only">내 질문: </span>
        {pending.request.question}
      </p>
      <p className="-mt-2 text-sm text-text-secondary">연결한 대상: {pending.labels.length > 0 ? pending.labels.join(" · ") : "없음"}</p>
      {pending.phase !== "unconfirmed" ? (
        <SkeletonLines lines={2} label={pending.phase === "sending" ? "질문을 보내고 있어요" : "응답을 받지 못해 질문이 접수됐는지 확인하고 있어요"} />
      ) : (
        <div role="alert" className="flex flex-col items-start gap-2">
          <p className="flex items-center gap-2 text-base font-semibold text-text-primary">
            <CircleAlert className="size-5 shrink-0 text-error" aria-hidden="true" />
            질문이 접수됐는지 확인하지 못했어요
          </p>
          <p className="max-w-prose text-base text-text-secondary">같은 질문을 다시 만들지 않고, 접수 상태만 다시 확인해요.</p>
          <Button variant="secondary" size="sm" onClick={onRecheck}>
            <RotateCw aria-hidden="true" />
            다시 확인
          </Button>
        </div>
      )}
    </>
  );
}
