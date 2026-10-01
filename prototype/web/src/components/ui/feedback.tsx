// 공통 상태 컴포넌트: Skeleton(로딩), EmptyState(빈 상태), ErrorState(오류).
// 규칙: 오류를 0건(빈 상태)으로 위장하지 않는다. 오류면 반드시 ErrorState를 쓴다(NFR-11).
import { ArrowLeft, CircleAlert, RotateCw } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { useNavigate } from "react-router";
import { ApiError } from "@/api/client";
import { errorReasonMessage } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-sm bg-surface-sunken", className)} {...props} />;
}

/** 로딩 중인 영역. 스크린리더에는 label만 읽힌다. */
export function LoadingBlock({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div aria-busy="true" className={className}>
      <p role="status" className="sr-only">
        {label}
      </p>
      {children}
    </div>
  );
}

export function SkeletonLines({ lines = 3, label = "불러오는 중이에요" }: { lines?: number; label?: string }) {
  return (
    <LoadingBlock label={label} className="flex flex-col gap-2">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-4", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </LoadingBlock>
  );
}

/** 목록(ListRow·EventRow)이 들어갈 자리의 로딩 모양. 행 + 구분선. */
export function SkeletonRows({ count = 3, label = "불러오는 중이에요" }: { count?: number; label?: string }) {
  return (
    <LoadingBlock label={label} className="flex flex-col divide-y divide-border-subtle">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex flex-col gap-2 py-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-4 w-1/3" />
        </div>
      ))}
    </LoadingBlock>
  );
}

interface EmptyStateProps {
  /** 지금 상태를 한 문장으로 (예: "아직 고른 관심 종목이 없어요") */
  title: string;
  /** 필요하면 이유·방법 한 문장 */
  description?: ReactNode;
  /** 다음 행동(버튼·링크). 막다른 길을 만들지 않도록 가능하면 항상 넣는다. */
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-start gap-2 py-8", className)}>
      <p className="text-lg font-semibold text-text-primary">{title}</p>
      {description && <p className="max-w-prose text-base text-text-secondary">{description}</p>}
      {action && <div className="mt-2 flex flex-wrap gap-2">{action}</div>}
    </div>
  );
}

interface ErrorStateProps {
  error?: unknown;
  title?: string;
  onRetry?: () => void;
  /** [이전 화면으로] 버튼을 보여줄지 */
  showBack?: boolean;
  /** 목록 한 칸처럼 좁은 자리 */
  compact?: boolean;
  className?: string;
}

/** 오류를 사용자 말로 바꾼다(상황 + 해결책). 내부 코드는 [자세히] 안에만 둔다. */
export function describeError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 0 || error.code === "bff_unreachable") {
      return { message: "서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.", code: error.code };
    }
    if (error.status >= 500) {
      return { message: "일시적인 서버 문제예요. 잠시 후 다시 시도해 주세요.", code: error.code };
    }
    return { message: errorReasonMessage(error.code) ?? "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.", code: error.code };
  }
  return { message: "예상하지 못한 문제가 생겼어요. 잠시 후 다시 시도해 주세요.", code: "unknown" };
}

export function ErrorState({ error, title = "정보를 불러오지 못했어요", onRetry, showBack, compact, className }: ErrorStateProps) {
  const navigate = useNavigate();
  const { message, code } = describeError(error);
  return (
    <div role="alert" className={cn("flex flex-col items-start gap-2", compact ? "py-2" : "py-8", className)}>
      <p className={cn("flex items-center gap-2 font-semibold text-text-primary", compact ? "text-base" : "text-lg")}>
        <CircleAlert className="size-5 shrink-0 text-error" aria-hidden="true" />
        {title}
      </p>
      <p className="max-w-prose text-base text-text-secondary">{message}</p>
      <details className="text-sm text-text-tertiary">
        <summary className="cursor-pointer">자세히</summary>
        <p className="mt-1 tabular-nums break-all">오류 코드: {code}</p>
      </details>
      {(onRetry || showBack) && (
        <div className="mt-2 flex flex-wrap gap-2">
          {onRetry && (
            <Button variant="secondary" size={compact ? "sm" : "md"} onClick={onRetry}>
              <RotateCw aria-hidden="true" />
              다시 시도
            </Button>
          )}
          {showBack && (
            <Button variant="ghost" size={compact ? "sm" : "md"} onClick={() => navigate(-1)}>
              <ArrowLeft aria-hidden="true" />
              이전 화면으로
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
