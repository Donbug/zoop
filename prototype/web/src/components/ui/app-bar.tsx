import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface AppBarProps {
  /** 왼쪽: 로고 또는 뒤로가기 버튼 */
  leading: ReactNode;
  /** 가운데: 화면 제목(선택). 없으면 leading이 제목 역할을 한다. */
  title?: ReactNode;
  /** 오른쪽: SourceIndicator, 계정 메뉴 등 */
  trailing?: ReactNode;
  className?: string;
}

/** 모바일(≤768px) 상단 한 줄 고정 바. 높이 48px, 화면 폭을 넘지 않는다. */
export function AppBar({ leading, title, trailing, className }: AppBarProps) {
  return (
    <div className={cn("flex h-12 min-w-0 items-center gap-2 pr-1 pl-4", className)}>
      <div className="flex shrink-0 items-center">{leading}</div>
      {title && <div className="min-w-0 flex-1 truncate text-lg font-semibold text-text-primary">{title}</div>}
      {trailing && <div className="ml-auto flex min-w-0 items-center gap-0.5">{trailing}</div>}
    </div>
  );
}
