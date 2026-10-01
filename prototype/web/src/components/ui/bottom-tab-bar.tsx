import type { LucideIcon } from "lucide-react";
import { NavLink } from "react-router";
import { cn } from "@/lib/utils";

export interface BottomTab {
  to: string;
  label: string;
  icon: LucideIcon;
  /** true면 하위 경로에서는 활성으로 보지 않는다("/" 같은 루트) */
  end?: boolean;
}

/**
 * 모바일(≤768px) 하단 고정 탭바. 높이 56px + 기기 안전 영역.
 * 현재 탭은 aria-current="page"(NavLink 기본) + 브랜드 색 + 굵은 글자로 표시한다.
 * 본문에는 pb-tabbar 유틸리티로 같은 만큼 아래 여백을 둔다.
 */
export function BottomTabBar({ tabs, label = "주요 메뉴", className }: { tabs: BottomTab[]; label?: string; className?: string }) {
  return (
    <nav
      aria-label={label}
      className={cn("fixed inset-x-0 bottom-0 z-30 border-t border-border-subtle bg-surface-raised pb-[env(safe-area-inset-bottom)]", className)}
    >
      <ul className="flex h-14">
        {tabs.map(({ to, label: tabLabel, icon: Icon, end }) => (
          <li key={to} className="flex min-w-0 flex-1">
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex w-full flex-col items-center justify-center gap-0.5 text-sm text-text-secondary transition-token focus-visible:-outline-offset-2",
                  isActive ? "font-semibold text-brand-primary" : "font-medium hover:text-text-primary",
                )
              }
            >
              <Icon className="size-6" aria-hidden="true" />
              {tabLabel}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
