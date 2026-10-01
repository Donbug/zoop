// AI 결과(챗봇 답변·브리핑 회차·핵심 이슈) 평가(FS066-01, D08): 도움이 됐어요 / 도움이 안 됐어요.
//  - 로그인 회원만 평가한다. 비회원·로그인 전에는 버튼 대신 로그인 안내를 둔다(서버도 403).
//  - 한 사람이 결과마다 평가 하나. 다른 쪽을 누르면 바뀌고, 눌린 쪽을 다시 누르면 취소한다. 화면은 원하는 최종 상태
//    (up·down·none)를 한 요청으로 보내므로 같은 요청을 다시 보내도 또 토글되지 않는다.
//  - 저장이 확인된 상태만 눌린 상태로 보인다. 실패하면 이전 확정 상태를 두고, [다시 시도]는 현재 상태를 다시 확인한 뒤 같은 목표
//    상태로 보낸다. 싫어요에는 이유를 짧게 덧붙일 수 있다(선택).
//  - 선택 상태는 aria-pressed와 채워진 아이콘 + 글자로 알린다(색만으로 구분하지 않는다).
//  - 뉴스 요약은 만드는 기능이 없어 평가 대상이 없다(버튼을 두지 않는다).
import { LogIn, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";
import { ApiError } from "@/api/client";
import { useMyFeedback, useRate, useSession, type FeedbackFeature, type FeedbackValue } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface FeedbackButtonsProps {
  feature: FeedbackFeature;
  targetId: string;
  /** 사용자가 본 결과의 버전(브리핑 회차의 graphVersion). 서버의 현재 버전과 다르면 저장하지 않는다. */
  targetVersion?: string | null;
  /** 접근 가능한 이름에 쓰는 대상 이름("이 답변", "이 브리핑") */
  subject: string;
  className?: string;
}

export function FeedbackButtons(props: FeedbackButtonsProps) {
  const session = useSession();
  const location = useLocation();
  if (!session.data) return null;
  if (session.data.kind !== "member")
    return (
      <p className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-secondary", props.className)}>
        <span>평가는 로그인한 회원만 남길 수 있어요.</span>
        <Link
          to="/login"
          state={{ from: location.pathname + location.search }}
          className="inline-flex min-h-11 items-center gap-1 font-medium text-brand-primary underline-offset-4 hover:underline"
        >
          <LogIn className="size-4" aria-hidden="true" />
          로그인하고 평가하기
        </Link>
      </p>
    );
  return <MemberFeedback {...props} />;
}

function MemberFeedback({ feature, targetId, targetVersion, subject, className }: FeedbackButtonsProps) {
  const mine = useMyFeedback(feature, targetId, true);
  const rate = useRate(feature, targetId, targetVersion);
  const [reasonOpen, setReasonOpen] = useState(false);
  const [reason, setReason] = useState("");
  const value = mine.data?.value ?? null;
  const busy = rate.isPending || mine.isFetching;

  const send = (body: { value: FeedbackValue; reason?: string }) =>
    rate.mutate(body, {
      onSuccess: (item) => {
        setReasonOpen(item.value === "down" && !body.reason);
        if (item.value !== "down") setReason("");
      },
    });

  const choose = (kind: "up" | "down") => send({ value: value === kind ? "none" : kind });

  const retry = async () => {
    const last = rate.variables;
    if (!last) return;
    await mine.refetch();
    send(last);
  };

  const sendReason = (event: FormEvent) => {
    event.preventDefault();
    const text = reason.trim();
    if (text) send({ value: "down", reason: text });
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
          <Button type="submit" variant="secondary" loading={rate.isPending}>
            보내기
          </Button>
        </form>
      )}
      {rate.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-sm font-medium text-error">
          <span>
            {rate.error instanceof ApiError && rate.error.status === 409
              ? "결과가 바뀌어 평가를 저장하지 않았어요. 화면을 새로 고친 뒤 다시 평가해 주세요."
              : "평가를 저장하지 못했어요. 이전 평가는 그대로예요."}
          </span>
          <Button variant="ghost" size="sm" onClick={() => void retry()} disabled={busy}>
            다시 시도
          </Button>
        </div>
      )}
    </div>
  );
}
