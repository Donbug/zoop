// 관리자 패널 레이아웃: 왼쪽 고정 내비게이션 + 본문. 사용자 앱 셸·하단 탭은 쓰지 않는다.
// 데스크톱 우선(1280–1440 기준, 최소 1024). 내비게이션은 지금 있는 기능만 둔다.
import { BarChart3, LayoutDashboard, LogOut, Moon, Newspaper, ScrollText, Sparkles, Sun, ThumbsUp, UserRound, Users, Workflow } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useAdminLogout, useAdminSession } from "./api";

const adminNav = [
  { to: "/admin", label: "대시보드", icon: LayoutDashboard, end: true },
  { to: "/admin/pipeline", label: "이슈 관제", icon: Workflow },
  { to: "/admin/ai", label: "AI 운영", icon: Sparkles },
  { to: "/admin/briefings", label: "브리핑 운영", icon: Newspaper },
  { to: "/admin/stats", label: "이용 통계", icon: BarChart3 },
  { to: "/admin/feedback", label: "선호도", icon: ThumbsUp },
  { to: "/admin/members", label: "회원 관리", icon: Users },
  { to: "/admin/audit", label: "감사 로그", icon: ScrollText },
];

export function AdminLayout() {
  const session = useAdminSession();
  const logout = useAdminLogout();
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const admin = session.data?.authenticated ? session.data.admin : null;

  return (
    <div className="flex min-h-dvh min-w-[1024px] bg-surface-base">
      <a
        href="#admin-main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-30 focus:rounded-sm focus:bg-surface-raised focus:px-3 focus:py-2"
      >
        본문으로 건너뛰기
      </a>
      <aside className="sticky top-0 flex h-dvh w-56 shrink-0 flex-col border-r border-border-subtle bg-surface-raised">
        <div className="flex h-14 items-center gap-1.5 px-5">
          <span className="text-xl font-bold tracking-tight text-text-primary">줍</span>
          <span className="text-sm font-semibold text-text-secondary">관리자</span>
        </div>
        <nav aria-label="관리자 메뉴" className="flex flex-1 flex-col gap-0.5 px-2 py-2">
          {adminNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex h-11 items-center gap-3 rounded-sm px-3 text-base transition-token [&_svg]:size-5 [&_svg]:shrink-0",
                  isActive ? "bg-surface-selected font-semibold text-text-primary" : "font-medium text-text-secondary hover:bg-surface-sunken hover:text-text-primary",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon aria-hidden="true" className={isActive ? "text-brand-primary" : undefined} />
                  {item.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="flex flex-col gap-1 border-t border-border-subtle px-2 py-3">
          {admin && (
            <p className="flex items-center gap-2 px-3 py-1 text-sm text-text-secondary">
              <UserRound className="size-4 shrink-0" aria-hidden="true" />
              <span className="min-w-0 truncate">{admin.displayName}</span>
            </p>
          )}
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" className="flex-1 justify-start" loading={logout.isPending} onClick={() => logout.mutate(undefined, { onSettled: () => navigate("/admin/login", { replace: true }) })}>
              <LogOut aria-hidden="true" />
              로그아웃
            </Button>
            <Button variant="ghost" size="icon" onClick={toggle} aria-label={theme === "dark" ? "라이트 테마로 바꾸기" : "다크 테마로 바꾸기"}>
              {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
            </Button>
          </div>
        </div>
      </aside>
      <main id="admin-main" className="flex min-w-0 flex-1 flex-col">
        <div className="mx-auto flex w-full max-w-[1440px] min-w-0 flex-1 flex-col gap-4 px-8 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
