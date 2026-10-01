// FocusBar: 포커스 모드(G2)에서 그래프 위에 뜨는 한 줄 막대. [표지] 이름 중심 · 1단계|2단계 · 전체 보기.
// 들어가기·범위 바꾸기·나가기는 주소 이력에 쌓여 뒤로 가기로도 돌아온다(부모가 처리).
import { X, Zap } from "lucide-react";
import { forwardRef } from "react";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Tooltip } from "@/components/ui/tooltip";
import type { FocusHops } from "@/lib/graph-view";
import { cn } from "@/lib/utils";
import { CompanyMark } from "./company-mark";

interface FocusBarProps {
  node: Schemas["GraphNode"];
  hops: FocusHops;
  onHopsChange: (hops: FocusHops) => void;
  onExit: () => void;
  /** 좁은 화면: 나가기 버튼을 아이콘만(툴팁·aria-label) 보여 한 줄을 지킨다. */
  compact?: boolean;
  className?: string;
}

export const FocusBar = forwardRef<HTMLDivElement, FocusBarProps>(function FocusBar({ node, hops, onHopsChange, onExit, compact, className }, ref) {
  const name = `${node.label} 중심`;
  return (
    <div
      ref={ref}
      role="region"
      aria-label={`${name} 보기`}
      tabIndex={-1}
      className={cn("flex min-w-0 items-center gap-2 rounded-sm bg-surface-raised py-1 pr-1 pl-3 shadow-overlay outline-none", className)}
    >
      {node.kind === "company" ? (
        <CompanyMark id={node.id} name={node.label} brandColor={node.brandColor} logoUrl={node.logoUrl} />
      ) : (
        <Zap className="size-5 shrink-0 text-text-secondary" aria-hidden="true" />
      )}
      <p className="min-w-0 flex-1 truncate text-base font-semibold text-text-primary" title={node.label}>
        {name}
      </p>
      <Segmented
        aria-label="이웃 범위"
        value={String(hops) as "1" | "2"}
        onValueChange={(value) => onHopsChange(Number(value) as FocusHops)}
        options={[
          { value: "1", label: "1단계", ariaLabel: "1단계: 바로 이어진 노드" },
          { value: "2", label: "2단계", ariaLabel: "2단계: 이웃의 이웃까지" },
        ]}
        className="shrink-0"
      />
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
