import type { LucideIcon } from "lucide-react";
import { NavLink } from "react-router";
import { cn } from "@/lib/utils";

interface TabBase {
  label: string;
  icon: LucideIcon;
}

/** 화면으로 이동하는 탭 */
export interface RouteTab extends TabBase {
  to: string;
  /** true면 하위 경로에서는 활성으로 보지 않는다("/" 같은 루트) */
  end?: boolean;
}

/** 화면을 옮기지 않고 창(대화상자)을 여는 탭. open은 그 창이 지금 열려 있는지. */
export interface ActionTab extends TabBase {
  id: string;
  onPress: () => void;
  open: boolean;
}

export type BottomTab = RouteTab | ActionTab;

const tabClass = (active: boolean) =>
  cn(
    "flex w-full flex-col items-center justify-center gap-0.5 text-sm transition-token focus-visible:-outline-offset-2",
    // 활성 탭: 색 + 굵은 글자 + 위쪽 2px 표시선(색만으로 구분하지 않는다)
    active ? "font-semibold text-brand-primary shadow-[inset_0_2px_0_var(--color-brand-primary)]" : "font-medium text-text-secondary hover:text-text-primary",
  );

/**
 * 모바일(≤768px) 하단 고정 탭바. 높이 56px + 기기 안전 영역. 탭 하나는 폭 1/n × 높이 56px(44px 이상).
 * 현재 탭은 aria-current="page"(NavLink 기본) + 브랜드 색 + 굵은 글자 + 위쪽 표시선으로 표시한다.
 * 창을 여는 탭(ActionTab)은 aria-expanded로 열림을 알리고, 그 창이 열려 있는 동안은 그 탭만 활성으로 보인다
 * (화면 탭의 aria-current는 그대로 둔다. 화면은 바뀌지 않았으므로).
 * 본문에는 pb-tabbar 유틸리티로 같은 만큼 아래 여백을 둔다.
 */
export function BottomTabBar({ tabs, label = "주요 메뉴", className }: { tabs: BottomTab[]; label?: string; className?: string }) {
  const actionOpen = tabs.some((tab) => "onPress" in tab && tab.open);
  return (
    <nav
      aria-label={label}
      className={cn("fixed inset-x-0 bottom-0 z-30 border-t border-border-subtle bg-surface-raised pb-[env(safe-area-inset-bottom)]", className)}
    >
      <ul className="flex h-14">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <li key={"to" in tab ? tab.to : tab.id} className="flex min-w-0 flex-1">
              {"to" in tab ? (
                <NavLink to={tab.to} end={tab.end} className={({ isActive }) => tabClass(isActive && !actionOpen)}>
                  <Icon className="size-6" aria-hidden="true" />
                  {tab.label}
                </NavLink>
              ) : (
                <button type="button" aria-haspopup="dialog" aria-expanded={tab.open} onClick={tab.onPress} className={tabClass(tab.open)}>
                  <Icon className="size-6" aria-hidden="true" />
                  {tab.label}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
