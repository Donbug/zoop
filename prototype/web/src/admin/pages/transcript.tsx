// AI 대화록 한 건(요구 75): 개인정보를 가린 사본. 저장된 원문은 바뀌지 않고, 이 화면을 여는 것은 감사 로그에 남는다.
import { ArrowLeft, Ban, CircleAlert, CircleCheck, Hourglass, ListChecks, MessageCircleQuestion, MessageSquareText, ShieldCheck, ShieldQuestion, ThumbsDown, ThumbsUp, type LucideIcon } from "lucide-react";
import { Link, useParams } from "react-router";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { useTranscript } from "../api";
import { AdminPageHeader, KstTime, StatusLabel, type StatusTone } from "../ui";

// 질문 한 건의 처리 결과(서버가 저장한 상태). 완료는 답변·되묻기·조건 안내·근거 부족, 그 밖에 실패·취소·처리 중이 있다.
const messageStatus: Record<string, { icon: LucideIcon; label: string; tone: StatusTone }> = {
  answered: { icon: CircleCheck, label: "답변함", tone: "success" },
  insufficient_evidence: { icon: ShieldQuestion, label: "근거 부족으로 보류", tone: "warning" },
  clarification: { icon: MessageCircleQuestion, label: "되물음", tone: "neutral" },
  guidance: { icon: ListChecks, label: "조건 안내", tone: "neutral" },
  failed: { icon: CircleAlert, label: "실패", tone: "error" },
  cancelled: { icon: Ban, label: "취소", tone: "neutral" },
  queued: { icon: Hourglass, label: "처리 중", tone: "neutral" },
  running: { icon: Hourglass, label: "처리 중", tone: "neutral" },
};

const maskedLabel: Record<string, string> = {
  email: "이메일",
  phone: "전화번호",
  rrn: "주민등록번호",
  card: "카드번호",
  account: "계좌번호",
  name: "이름",
};

export function AdminTranscriptPage() {
  const { id = "" } = useParams();
  const transcript = useTranscript(id);
  const data = transcript.data;
  const back = "/admin/feedback?tab=transcripts";

  return (
    <>
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link to={back}>
            <ArrowLeft aria-hidden="true" />
            AI 대화록
          </Link>
        </Button>
      </div>
      <AdminPageHeader title="AI 대화록" icon={MessageSquareText} />
      {transcript.isPending && <SkeletonRows count={3} label="대화록을 불러오고 있어요" />}
      {transcript.isError &&
        (transcript.error instanceof ApiError && transcript.error.status === 404 ? (
          <EmptyState title="찾는 대화록이 없어요" action={<Link to={back} className="font-medium text-brand-primary hover:underline">대화록 목록으로 가기</Link>} />
        ) : (
          <ErrorState error={transcript.error} title="대화록을 불러오지 못했어요" onRetry={() => void transcript.refetch()} />
        ))}
      {data && (
        <>
          <p className="text-sm text-text-secondary">
            <span className="font-mono">{data.user}</span> · {data.userKind === "member" ? "회원" : "비회원"} · 시작 <KstTime value={data.startedAt} seconds /> · 질문 {data.messages.length}개
          </p>
          <div role="note" className="flex items-start gap-2 border-y border-border-subtle py-3 text-base text-text-primary">
            <ShieldCheck className="mt-0.5 size-5 shrink-0 text-brand-primary" aria-hidden="true" />
            <div className="flex flex-col gap-0.5">
              <p className="font-medium">개인정보를 가린 사본이에요. 저장된 원문은 바뀌지 않았고, 이 열람은 감사 로그에 남았어요.</p>
              <p className="text-sm text-text-secondary">
                가리는 항목: {data.masking.rules.join(" · ")}.{" "}
                {Object.keys(data.masking.counts).length > 0
                  ? `이 대화에서 가린 것: ${Object.entries(data.masking.counts)
                      .map(([kind, count]) => `${maskedLabel[kind] ?? kind} ${count}건`)
                      .join(" · ")}`
                  : "이 대화에서는 가릴 항목이 없었어요."}
              </p>
            </div>
          </div>
          <ol className="flex flex-col divide-y divide-border-subtle">
            {data.messages.map((message) => (
              <li key={message.id} className="flex flex-col gap-2 py-4">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-secondary">
                  <span className="font-medium text-text-primary">질문 {message.seq}</span>
                  <KstTime value={message.at} seconds />
                  <StatusLabel {...(messageStatus[message.status] ?? { icon: CircleAlert, label: message.status, tone: "neutral" as const })} />
                  <span>근거 인용 {message.citationCount}건</span>
                </div>
                <p className="text-base font-semibold text-text-primary">
                  <span className="sr-only">질문: </span>
                  {message.question}
                </p>
                <p className="text-base leading-relaxed whitespace-pre-line text-text-primary">
                  <span className="sr-only">답변: </span>
                  {message.answer}
                </p>
                {message.contextLabels.length > 0 && <p className="text-sm text-text-secondary">연결한 대상: {message.contextLabels.join(" · ")}</p>}
                {(message.feedback.up > 0 || message.feedback.down > 0) && (
                  <div className="flex flex-col gap-1 text-sm text-text-secondary">
                    <p className="flex items-center gap-3 tabular-nums">
                      <span className="inline-flex items-center gap-1">
                        <ThumbsUp className="size-4" aria-hidden="true" />
                        좋아요 {message.feedback.up}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <ThumbsDown className="size-4" aria-hidden="true" />
                        싫어요 {message.feedback.down}
                      </span>
                    </p>
                    {message.feedback.reasons.map((reason, index) => (
                      <p key={index}>싫어요 사유: {reason}</p>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </>
  );
}
