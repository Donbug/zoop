// PathBar: 경로 모드(G6)에서 그래프 위에 뜨는 한 줄 막대. [표지] A ↔ [표지] B · N단계 · ✕(전체 보기).
// FocusBar와 같은 떠 있는 표면이다. 들어가기·나가기는 주소 이력(?path=)에 쌓여 뒤로 가기로도 돌아온다(부모가 처리).
import { ArrowLeftRight, ListOrdered, X } from "lucide-react";
import { forwardRef } from "react";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { CompanyMark } from "./company-mark";

interface PathBarProps {
  from: Schemas["GraphNode"];
  to: Schemas["GraphNode"];
  /** 경로의 선 수 */
  steps: number;
  onExit: () => void;
  /** 좁은 화면에서 닫아 둔 단계 목록(시트)을 다시 연다. 없으면 버튼을 두지 않는다. */
  onShowSteps?: () => void;
  /** 좁은 화면: 나가기 버튼을 아이콘만(툴팁·aria-label) 보여 한 줄을 지킨다. */
  compact?: boolean;
  className?: string;
}

export const PathBar = forwardRef<HTMLDivElement, PathBarProps>(function PathBar({ from, to, steps, onExit, onShowSteps, compact, className }, ref) {
  const name = `${from.label}에서 ${to.label}까지 경로`;
  return (
    <div
      ref={ref}
      role="region"
      aria-label={name}
      tabIndex={-1}
      className={cn("flex min-w-0 items-center rounded-sm bg-surface-raised py-1 pr-1 pl-3 shadow-overlay outline-none", compact ? "gap-0" : "gap-2", className)}
    >
      <p className={cn("flex min-w-0 flex-1 items-center text-base font-semibold text-text-primary", compact ? "gap-1" : "gap-2")}>
        <span className="sr-only">{name}, </span>
        <CompanyMark id={from.id} name={from.label} brandColor={from.brandColor} logoUrl={from.logoUrl} />
        <span className="min-w-0 truncate" title={from.label} aria-hidden="true">
          {from.label}
        </span>
        <ArrowLeftRight className="size-4 shrink-0 text-text-secondary" aria-hidden="true" />
        <CompanyMark id={to.id} name={to.label} brandColor={to.brandColor} logoUrl={to.logoUrl} />
        <span className="min-w-0 truncate" title={to.label} aria-hidden="true">
          {to.label}
        </span>
        <span className="shrink-0 font-normal text-text-secondary tabular-nums">· {steps}단계</span>
      </p>
      {onShowSteps && (
        <Tooltip content="경로 단계 보기">
          <Button variant="ghost" size="icon" aria-label="경로 단계 보기" onClick={onShowSteps} className="shrink-0">
            <ListOrdered aria-hidden="true" />
          </Button>
        </Tooltip>
      )}
      {compact ? (
        <Tooltip content="전체 보기">
          <Button variant="ghost" size="icon" aria-label="전체 보기" onClick={onExit} className="shrink-0">
            <X aria-hidden="true" />
          </Button>
        </Tooltip>
      ) : (
        <Button variant="ghost" size="sm" onClick={onExit} className="shrink-0">
          <X aria-hidden="true" />
          전체 보기
        </Button>
      )}
    </div>
  );
});
