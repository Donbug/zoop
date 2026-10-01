// 사건이 PoC 검증만으로 게시된 것이 아닐 때의 출처 표시(관리자 승인·자동 검수 규칙)와, 규칙이 비운 역할 자리 표시.
import { CircleHelp, Info, ListChecks, UserCheck } from "lucide-react";
import type { Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { IconHint } from "@/components/ui/icon-hint";
import { cn } from "@/lib/utils";

/** 승인 출처 한 줄: 배지(관리자 승인 / 자동 검수 규칙) + 눌러 보는 짧은 설명. 승인 표시가 없으면 아무것도 그리지 않는다. */
export function ApprovalNote({ approval, className }: { approval: Schemas["ApprovalOut"] | null | undefined; className?: string }) {
  if (!approval) return null;
  const byAdmin = approval.source === "admin-review";
  const Icon = byAdmin ? UserCheck : ListChecks;
  return (
    <p className={cn("flex items-center gap-1", className)}>
      <Badge>
        <Icon aria-hidden="true" />
        {approval.label}
      </Badge>
      <IconHint icon={Info} label={byAdmin ? "관리자가 원문 근거를 직접 확인하고 게시했어요" : "역할 표현을 확인하지 못해 비우고 게시했어요"}>
        {byAdmin ? (
          <p>AI 검증이 보류했던 내용을 관리자가 원문 인용으로 확인했어요.</p>
        ) : (
          <p>사건과 원문 인용은 AI 검증을 통과했어요. 확인하지 못한 역할은 ‘역할 미확인’으로 보여요.</p>
        )}
        {byAdmin && approval.ruleId && <p>같은 사건에 자동 검수 규칙으로 게시된 내용도 있어요.</p>}
      </IconHint>
    </p>
  );
}

/** 자동 검수 규칙이 비운 역할 자리. 다른 역할로 채우지 않고, 값이 없다는 사실만 알린다. */
export function RoleUnconfirmed({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <CircleHelp className="size-3.5 shrink-0" aria-hidden="true" />
      역할 미확인
    </span>
  );
}
