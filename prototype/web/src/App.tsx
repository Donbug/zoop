// 라우트 목록. 화면 ID는 docs/design/design-direction.md §5를 따른다.
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { createBrowserRouter, Link, RouterProvider } from "react-router";
import { api, ApiError, type Schemas } from "@/api/client";
import { EmptyState, LoadingBlock } from "@/components/ui/feedback";
import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { clearPersonalCache, queryKeys } from "@/api/queries";
import { AppLayout, RedirectIfSignedIn, RequireOnboarding, RequireSession } from "@/features/app-shell";
import { BriefingPage } from "@/pages/briefing-page";
import { CompanyPage } from "@/pages/company-page";
import { CompaniesPage } from "@/pages/companies-page";
import { DesignSystemPage } from "@/pages/design-system-page";
import { LoginPage } from "@/pages/login-page";
import { MainPage } from "@/pages/main-page";
import { MockIdpPage } from "@/pages/mock-idp-page";
import { MyStocksPage } from "@/pages/my-stocks-page";
import { OnboardingPage } from "@/pages/onboarding-page";
import { SignupPage } from "@/pages/signup-page";

// 관리자 패널(요구 76·77·79–82): 사용자 번들과 분리된 청크. 사용자 앱 셸 밖에서 자체 레이아웃을 쓴다.
const AdminRoot = lazy(() => import("@/admin/admin-root"));

// 차단된 회원(member_blocked 401): 서버 세션을 로그아웃으로 폐기하고 개인 캐시를 비운 뒤 시작 화면에서 안내한다.
// 여러 조회가 동시에 같은 오류를 받아도 한 번만 처리한다.
let leavingBlocked = false;
async function onApiError(error: unknown) {
  if (!(error instanceof ApiError) || error.code !== "member_blocked" || error.status !== 401 || leavingBlocked) return;
  leavingBlocked = true;
  try {
    await api<void>("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    clearPersonalCache(queryClient);
    // 가드가 먼저 /login(안내 없음)으로 보내지 않도록, 세션을 익명으로 바꾸는 즉시 안내 주소로 옮긴다.
    queryClient.setQueryData<Schemas["SessionResponse"]>(queryKeys.session, (prev) =>
      prev && { ...prev, authenticated: false, kind: "anonymous", user: null, setup: null },
    );
    await router.navigate("/login?notice=blocked", { replace: true });
    await queryClient.invalidateQueries({ queryKey: queryKeys.session });
  } finally {
    leavingBlocked = false;
  }
}

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onApiError }),
  mutationCache: new MutationCache({ onError: onApiError }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // 4xx는 다시 시도해도 같으므로 바로 오류를 보여주고, 서버 장애(5xx·연결 실패)만 한 번 더 시도한다.
      retry: (count, error) => error instanceof ApiError && (error.status === 0 || error.status >= 500) && count < 1,
    },
  },
});

function NotFound() {
  return (
    <EmptyState
      title="찾는 화면이 없어요"
      description="주소를 확인하거나 지도로 돌아가 보세요."
      action={
        <Link to="/" className="font-medium text-brand-primary hover:underline">
          지도로 돌아가기
        </Link>
      }
      className="py-20"
    />
  );
}

const router = createBrowserRouter([
  {
    path: "/admin/*",
    element: (
      <Suspense fallback={<LoadingBlock label="관리자 화면을 불러오고 있어요">{null}</LoadingBlock>}>
        <AdminRoot />
      </Suspense>
    ),
  },
  // 개발용 모의 소셜 로그인 제공자의 동의 화면(앱 밖의 제공자 화면을 흉내 낸다. 앱 셸을 쓰지 않는다).
  { path: "/mock-idp", element: <MockIdpPage /> },
  {
    element: <AppLayout />,
    children: [
      { path: "/design-system", element: <DesignSystemPage /> }, // 디자인시스템 (로그인 없이 열람)
      {
        element: <RedirectIfSignedIn />,
        children: [
          { path: "/login", element: <LoginPage /> }, // UI-01 시작 화면
          { path: "/signup", element: <SignupPage /> }, // 이메일 회원가입
        ],
      },
      {
        element: <RequireOnboarding />,
        children: [{ path: "/onboarding", element: <OnboardingPage /> }], // UI-02
      },
      {
        element: <RequireSession />,
        children: [
          { path: "/", element: <MainPage /> }, // UI-03 + UI-04/05 패널 + UI-09/10 창
          { path: "/companies", element: <CompaniesPage /> }, // FS037 종목 목록·검색
          { path: "/companies/:id", element: <CompanyPage /> }, // UI-06 (+UI-07 통합)
          { path: "/briefing", element: <BriefingPage /> }, // UI-08
          { path: "/me/stocks", element: <MyStocksPage /> }, // 내 종목 (v2 §5.8)
        ],
      },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
