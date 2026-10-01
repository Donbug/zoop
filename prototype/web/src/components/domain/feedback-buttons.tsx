// AI 출력(챗봇 답변·브리핑 회차·핵심 이슈) 평가(요구 75): 도움이 됐어요 / 도움이 안 됐어요.
// 한 사람이 대상마다 표 하나. 눌린 버튼을 다시 누르면 취소되고, 다른 쪽을 누르면 바뀐다. 싫어요는 이유를 짧게 덧붙일 수 있다(선택).
// 선택 상태는 aria-pressed와 채워진 아이콘 + 글자로 알린다(색만으로 구분하지 않는다).
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useCancelVote, useMyFeedback, useVote, type FeedbackFeature } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface FeedbackButtonsProps {
  feature: FeedbackFeature;
  targetId: string;
  /** 접근 가능한 이름에 쓰는 대상 이름("이 답변", "이 브리핑") */
  subject: string;
  className?: string;
}

export function FeedbackButtons({ feature, targetId, subject, className }: FeedbackButtonsProps) {
  const mine = useMyFeedback(feature, targetId);
  const vote = useVote(feature, targetId);
  const cancel = useCancelVote(feature, targetId);
  const [reasonOpen, setReasonOpen] = useState(false);
  const [reason, setReason] = useState("");
  const value = mine.data?.value ?? null;
  const busy = vote.isPending || cancel.isPending;
  const failed = vote.isError || cancel.isError;

  const choose = (next: "up" | "down") => {
    if (value === next) {
      setReasonOpen(false);
      cancel.mutate();
      return;
    }
    vote.mutate({ value: next }, { onSuccess: () => setReasonOpen(next === "down") });
  };

  const sendReason = (event: FormEvent) => {
    event.preventDefault();
    const text = reason.trim();
    if (text) vote.mutate({ value: "down", reason: text }, { onSuccess: () => setReasonOpen(false) });
    else setReasonOpen(false);
  };

  const toggle = (kind: "up" | "down", label: string, Icon: typeof ThumbsUp) => (
    <Button
      variant="ghost"
      size="icon"
      aria-pressed={value === kind}
      aria-label={`${subject}: ${label}`}
      disabled={busy || mine.isPending}
      onClick={() => choose(kind)}
      className={cn("size-9", value === kind && "bg-surface-selected text-brand-primary")}
    >
      <Icon className={cn("size-5", value === kind && "fill-current")} aria-hidden="true" />
    </Button>
  );

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div role="group" aria-label={`${subject} 평가`} className="flex items-center gap-1">
        {toggle("up", "도움이 됐어요", ThumbsUp)}
        {toggle("down", "도움이 안 됐어요", ThumbsDown)}
        <span role="status" className="text-sm text-text-secondary">
          {value === "up" && "도움이 됐다고 남겼어요"}
          {value === "down" && "도움이 안 됐다고 남겼어요"}
        </span>
      </div>
      {reasonOpen && value === "down" && (
        <form onSubmit={sendReason} className="flex items-end gap-2">
          <Input label="이유(선택)" className="min-w-0 flex-1" placeholder="어떤 점이 아쉬웠나요?" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button type="submit" variant="secondary" loading={vote.isPending}>
            보내기
          </Button>
        </form>
      )}
      {failed && (
        <p role="alert" className="text-sm font-medium text-error">
          의견을 저장하지 못했어요. 잠시 뒤에 다시 눌러 주세요.
        </p>
      )}
    </div>
  );
}
