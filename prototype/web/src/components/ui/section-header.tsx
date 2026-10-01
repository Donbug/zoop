import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface SectionHeaderProps {
  /** 섹션 제목(18px semibold). 제목 위에 알약 라벨을 달지 않는다. */
  title: ReactNode;
  /** 제목 앞 아이콘(장식). 같은 종류의 섹션은 앱 전체에서 같은 아이콘을 쓴다(기업 Building2, 사건 Zap …). */
  icon?: LucideIcon;
  /** 오른쪽: 행동 하나(링크·버튼) 또는 설명을 담은 IconHint. 설명문을 제목 밑에 늘어놓지 않는다. */
  action?: ReactNode;
  as?: "h2" | "h3";
  /** 섹션의 aria-labelledby에 연결할 id */
  id?: string;
  className?: string;
}

/** 목록 위 머리글. 제목이 폭 대부분을 차지하고, 행동은 오른쪽 끝에 붙는다. */
export function SectionHeader({ title, icon: Icon, action, as: Heading = "h2", id, className }: SectionHeaderProps) {
  return (
    <div className={cn("flex items-center gap-3 px-4 pt-6 pb-2", className)}>
      <Heading id={id} className="flex min-w-0 flex-1 items-center gap-2 text-lg leading-snug font-semibold text-text-primary">
        {Icon && <Icon className="size-5 shrink-0 text-text-secondary" aria-hidden="true" />}
        <span className="min-w-0">{title}</span>
      </Heading>
      {action && <div className="flex shrink-0 items-center gap-1">{action}</div>}
    </div>
  );
}
