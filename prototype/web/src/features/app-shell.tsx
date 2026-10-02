// 앱 셸(전역 헤더·모바일 탭바)과 인증 가드.
// - 데스크톱(>768px): 한 줄 헤더 [로고 · 지도 · 브리핑 · 내 종목 | 출처 · 테마 · 계정 메뉴]
// - 모바일(≤768px): 한 줄 AppBar [로고 | 출처 · 테마 · 계정 메뉴] + 하단 BottomTabBar(지도 · 브리핑 · 내 종목)
// - 디자인시스템 링크는 소비자 내비게이션이 아니라 계정 메뉴 안에 둔다.
// 가드 규칙: 로그인 안 함 → /login(가려던 주소를 state.from에 담아 로그인 후 복귀), 회원인데 초기 설정 미완료 → /onboarding,
// 비회원은 시장 전체 모드만. 튜토리얼은 메인 지도 위에서 진행한다(features/graph-tutorial.tsx).
// 화면 전환 실패(FS001): 접속 정보를 처음 확인하지 못했거나 화면을 그리다 실패하면 그 자리에 안내와 [다시 시도]를 둔다.
// 다시 시도해도 실패하면 사용자가 [시작 화면으로]를 골라 돌아간다(자동으로 돌려보내는 횟수 기준은 명세에 없어 두지 않는다).
// 이미 받은 접속 정보를 새로 확인하다 실패하면 지금 화면을 그대로 둔다.
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Bookmark, CircleHelp, LogIn, LogOut, Map as MapIcon, Moon, Newspaper, Palette, Sun, UserRound } from "lucide-react";
import { Component, Fragment, useRef, type ReactNode } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import type { Schemas } from "@/api/client";
import { useHealth, useLogout, useSession } from "@/api/queries";
import { SourceIndicator } from "@/components/domain/source-indicator";
import { AppBar } from "@/components/ui/app-bar";
import { BottomTabBar, type BottomTab } from "@/components/ui/bottom-tab-bar";
import { Button } from "@/components/ui/button";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { useMediaQuery, useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { OverlayProvider } from "./overlays";

/** 회원의 초기 설정(투자 여부·계좌·관심 종목)이 끝났는지. 비회원은 초기 설정이 없다. */
export function isSetupDone(session: Schemas["SessionResponse"]) {
  return session.kind !== "member" || Boolean(session.setup?.completed);
}

/** 로그인 화면으로 넘긴 '가려던 주소'. 같은 앱 안의 경로만 받는다. */
export function returnPath(state: unknown): string | null {
  const from = (state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("//") && !from.startsWith("/login") ? from : null;
}

const mainTabs: BottomTab[] = [
  { to: "/", label: "지도", icon: MapIcon, end: true },
  { to: "/briefing", label: "브리핑", icon: Newspaper },
  { to: "/me/stocks", label: "내 종목", icon: Bookmark },
];

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label={theme === "dark" ? "라이트 테마로 바꾸기" : "다크 테마로 바꾸기"}>
      {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  );
}

function Logo() {
  return (
    <Link to="/" className="flex h-11 items-center gap-1.5 rounded-sm" aria-label="줍 Zoop 홈">
      <span className="text-xl font-bold tracking-tight text-text-primary">줍</span>
      <span className="text-sm font-semibold text-text-secondary">Zoop</span>
    </Link>
  );
}

const menuItemClass =
  "flex h-11 cursor-pointer items-center gap-3 rounded-sm px-3 text-base text-text-primary outline-none select-none data-highlighted:bg-surface-sunken [&_svg]:size-5 [&_svg]:text-text-secondary";

/** 계정 메뉴: 이름/비회원 표시, 로그인·로그아웃, 디자인시스템(개발자용) 링크 */
function AccountMenu({ session, showName }: { session: Schemas["SessionResponse"] | undefined; showName: boolean }) {
  const logout = useLogout();
  const navigate = useNavigate();
  const kind = session?.authenticated ? session.kind : "anonymous";
  const name = kind === "member" ? `${session?.user?.displayName ?? "회원"}님` : kind === "guest" ? "비회원 체험 중" : null;
  const leave = () => logout.mutate(undefined, { onSettled: () => navigate("/login", { replace: true }) });
  // 튜토리얼을 다시 열면 포커스는 튜토리얼 제목이 가져간다(메뉴 버튼으로 되돌리지 않는다).
  const tourOpening = useRef(false);

  return (
    // 비모달: 모달 메뉴는 뒤쪽 전체에 aria-hidden을 걸어 포커스 가능한 요소가 숨겨진 트리에 남는다(axe aria-hidden-focus).
    // 메뉴는 Esc·바깥 클릭·항목 선택으로 닫히고 화살표 키 탐색은 그대로다.
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger asChild>
        <Button variant="ghost" size={showName && name ? "md" : "icon"} aria-label={name ? `계정 메뉴: ${name}` : "메뉴"} className={cn(showName && name && "px-3")}>
          <UserRound aria-hidden="true" />
          {showName && name && <span className="text-sm">{name}</span>}
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          collisionPadding={8}
          className="z-50 flex min-w-56 flex-col rounded-lg bg-surface-overlay p-2 shadow-overlay motion-pop"
          onCloseAutoFocus={(e) => {
            if (!tourOpening.current) return;
            tourOpening.current = false;
            e.preventDefault();
            document.getElementById("tutorial-title")?.focus();
          }}
        >
          {name && <DropdownMenu.Label className="px-3 py-2 text-sm text-text-secondary">{name}</DropdownMenu.Label>}
          {kind !== "anonymous" && (
            <DropdownMenu.Item
              className={menuItemClass}
              onSelect={() => {
                tourOpening.current = true;
                navigate("/?tour=1");
              }}
            >
              <CircleHelp aria-hidden="true" />
              튜토리얼 다시 보기
            </DropdownMenu.Item>
          )}
          {kind === "guest" && (
            <DropdownMenu.Item className={menuItemClass} onSelect={leave}>
              <LogIn aria-hidden="true" />
              로그인하기
            </DropdownMenu.Item>
          )}
          {kind === "member" && (
            <DropdownMenu.Item className={menuItemClass} onSelect={leave}>
              <LogOut aria-hidden="true" />
              로그아웃
            </DropdownMenu.Item>
          )}
          {kind !== "anonymous" && <DropdownMenu.Separator className="mx-1 my-1 h-px bg-border-subtle" />}
          <DropdownMenu.Item asChild className={menuItemClass}>
            <Link to="/design-system">
              <Palette aria-hidden="true" />
              디자인시스템
            </Link>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function AppHeader({ showNav, session }: { showNav: boolean; session: Schemas["SessionResponse"] | undefined }) {
  const health = useHealth();
  const isMobile = useMediaQuery("(max-width: 768px)");
  const source = <SourceIndicator kind={health.data?.datasetKind} offline={health.isError} />;

  return (
    <header className="sticky top-0 z-20 border-b border-border-subtle bg-surface-raised">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-30 focus:rounded-sm focus:bg-surface-raised focus:px-3 focus:py-2"
      >
        본문으로 건너뛰기
      </a>
      {isMobile ? (
        <AppBar
          leading={<Logo />}
          trailing={
            <>
              {source}
              <ThemeToggle />
              <AccountMenu session={session} showName={false} />
            </>
          }
        />
      ) : (
        <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-6 px-6">
          <Logo />
          {showNav && (
            <nav aria-label="주요 메뉴" className="flex h-full items-stretch">
              {mainTabs.map((tab) => (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  end={tab.end}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2 px-3 text-base whitespace-nowrap transition-token focus-visible:-outline-offset-2 [&_svg]:size-5",
                      isActive
                        ? "font-semibold text-brand-primary shadow-[inset_0_-2px_0_var(--color-brand-primary)]"
                        : "font-medium text-text-secondary hover:text-text-primary",
                    )
                  }
                >
                  <tab.icon aria-hidden="true" />
                  {tab.label}
                </NavLink>
              ))}
            </nav>
          )}
          <div className="ml-auto flex items-center gap-1">
            {source}
            <ThemeToggle />
            <AccountMenu session={session} showName />
          </div>
        </div>
      )}
    </header>
  );
}

function FullPageLoading() {
  return (
    <div aria-busy="true" className="mx-auto flex w-full max-w-3xl flex-col gap-3 p-8">
      <p role="status" className="sr-only">
        접속 정보를 확인하고 있어요
      </p>
      <Skeleton className="h-8 w-1/3" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

/** FS001 화면을 불러오지 못했을 때: 다시 시도, 그래도 안 되면 시작 화면으로(로그인·둘러보기 중이면 접속을 끝내고).
 *  접속 정보는 부모가 넘긴다. 여기서 세션 조회를 새로 구독하면 실패한 조회를 다시 불러 오류·로딩을 오가게 된다. */
function ScreenLoadError({ error, onRetry, signedIn }: { error: unknown; onRetry: () => void; signedIn: boolean }) {
  const location = useLocation();
  const navigate = useNavigate();
  const logout = useLogout();
  const toStart = () => (signedIn ? logout.mutate(undefined, { onSettled: () => navigate("/login") }) : navigate("/login"));
  return (
    <div className="mx-auto w-full max-w-xl px-4 md:px-8">
      {/* 화면 제목이 그려지기 전에 실패했으므로 문서 제목 자리를 채운다(보이는 안내 제목은 아래 오류 상태). */}
      <h1 className="sr-only">화면 오류</h1>
      <ErrorState
        error={error}
        title="화면을 불러오지 못했어요"
        message={
          location.pathname === "/login"
            ? "다시 시도해 주세요."
            : `다시 시도해 주세요. 계속 안 되면 시작 화면으로 돌아가 다른 방법으로 시작할 수 있어요.${signedIn ? " 이때 지금 접속은 끝나요." : ""}`
        }
        onRetry={onRetry}
        actions={
          location.pathname !== "/login" && (
            <Button variant="ghost" onClick={toStart} loading={logout.isPending}>
              시작 화면으로
            </Button>
          )
        }
      />
    </div>
  );
}

/** 화면(경로 요소)을 그리다 난 오류를 받아 FS001 안내로 바꾼다. 다시 시도는 그 화면을 새로 그린다. 경로가 바뀌면 새로 만든다(부모 key). */
class ScreenBoundary extends Component<{ children: ReactNode; signedIn: boolean }, { failed: boolean; error: unknown; attempt: number }> {
  state = { failed: false, error: null as unknown, attempt: 0 };

  static getDerivedStateFromError(error: unknown) {
    return { failed: true, error };
  }

  render() {
    if (this.state.failed) {
      return (
        <ScreenLoadError
          error={this.state.error}
          signedIn={this.props.signedIn}
          onRetry={() => this.setState((s) => ({ failed: false, error: null, attempt: s.attempt + 1 }))}
        />
      );
    }
    return <Fragment key={this.state.attempt}>{this.props.children}</Fragment>;
  }
}

function SessionGate({ children }: { children: (session: Schemas["SessionResponse"]) => ReactNode }) {
  const session = useSession();
  if (session.isPending) return <FullPageLoading />;
  // 이미 받은 접속 정보가 있으면 새로 확인하다 실패해도 지금 화면을 유지한다.
  if (!session.data) return <ScreenLoadError error={session.error} signedIn={false} onRetry={() => void session.refetch()} />;
  return <>{children(session.data)}</>;
}

/** 로그인(또는 비회원 체험)과 초기 설정이 끝난 사용자만 통과시킨다. */
export function RequireSession() {
  const location = useLocation();
  return (
    <SessionGate>
      {(session) => {
        if (!session.authenticated || session.kind === "anonymous")
          return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
        if (!isSetupDone(session)) return <Navigate to="/onboarding" replace />;
        return <Outlet />;
      }}
    </SessionGate>
  );
}

/** 온보딩은 초기 설정이 끝나지 않은 회원만. 끝났으면 메인으로 바로 보낸다(재방문 메인 직행). */
export function RequireOnboarding() {
  return (
    <SessionGate>
      {(session) => {
        if (!session.authenticated || session.kind === "anonymous") return <Navigate to="/login" replace />;
        if (session.kind !== "member" || isSetupDone(session)) return <Navigate to="/" replace />;
        return <Outlet />;
      }}
    </SessionGate>
  );
}

/** 이미 들어온 사용자는 시작 화면 대신 다음 화면(가려던 주소 → 메인, 설정 미완료면 초기 설정)으로 보낸다. */
export function RedirectIfSignedIn() {
  const location = useLocation();
  return (
    <SessionGate>
      {(session) => {
        if (session.authenticated && session.kind !== "anonymous")
          return <Navigate to={isSetupDone(session) ? (returnPath(location.state) ?? "/") : "/onboarding"} replace />;
        return <Outlet />;
      }}
    </SessionGate>
  );
}

export function AppLayout() {
  const session = useSession();
  const isMobile = useMediaQuery("(max-width: 768px)");
  const user = session.data;
  const location = useLocation();
  // 메뉴는 앱에 들어온 뒤(비회원 체험 포함, 온보딩 완료)에만 보인다. 로그인·온보딩 화면에서는 숨긴다.
  const showNav = Boolean(user?.authenticated && user.kind !== "anonymous" && isSetupDone(user));
  const showTabBar = showNav && isMobile;

  return (
    // 사용자가 바뀌면(로그인·로그아웃·비회원 시작) 근거·AI 질문 창 상태를 새로 만든다(이전 대화가 남지 않게).
    <OverlayProvider key={user?.user?.id ?? user?.kind ?? "loading"}>
      <div className="flex min-h-dvh flex-col">
        <AppHeader showNav={showNav} session={user} />
        <main id="main" className={cn("flex min-h-0 flex-1 flex-col", showTabBar && "pb-tabbar")}>
          {/* 화면 전환: 경로가 바뀌면 새 화면이 짧게 떠오른다(동작 줄이기에서는 즉시). */}
          <div key={location.pathname} className="motion-page flex min-h-0 flex-1 flex-col">
            <ScreenBoundary signedIn={Boolean(user?.authenticated && user.kind !== "anonymous")}>
              <Outlet />
            </ScreenBoundary>
          </div>
        </main>
        {showTabBar && <BottomTabBar tabs={mainTabs} />}
      </div>
    </OverlayProvider>
  );
}
