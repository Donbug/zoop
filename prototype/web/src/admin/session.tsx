// 관리자 세션 가드. 회원 세션과 완전히 분리된다(회원 쿠키로는 통과하지 못함).
// - 세션이 없거나 만료되면 /admin/login으로 보내고, 로그인 뒤 원래 경로(쿼리 포함)로 돌아온다.
// - 화면을 쓰는 도중 어떤 관리자 요청이든 401을 받으면 같은 방식으로 로그인 화면으로 보낸다.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { adminKeys, setUnauthorizedHandler, useAdminSession } from "./api";

export interface AdminLoginState {
  from?: string;
  reason?: "expired" | "required";
}

/** 관리자 요청이 401을 받으면 세션 캐시를 비우고 로그인 화면으로 보낸다. */
function useUnauthorizedRedirect() {
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const from = `${location.pathname}${location.search}`;
  useEffect(() => {
    setUnauthorizedHandler((code) => {
      client.removeQueries({ queryKey: adminKeys.all });
      const state: AdminLoginState = { from, reason: code === "admin_session_expired" ? "expired" : "required" };
      navigate("/admin/login", { replace: true, state });
    });
    return () => setUnauthorizedHandler(null);
  }, [client, from, navigate]);
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const session = useAdminSession();
  const location = useLocation();
  useUnauthorizedRedirect();

  if (session.isPending) {
    return (
      <div aria-busy="true" className="flex flex-col gap-3 p-8">
        <p role="status" className="sr-only">
          관리자 접속 정보를 확인하고 있어요
        </p>
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (session.isError) {
    return (
      <div className="p-8">
        <ErrorState error={session.error} title="관리자 접속 정보를 확인하지 못했어요" onRetry={() => void session.refetch()} />
      </div>
    );
  }
  if (!session.data.authenticated) {
    const state: AdminLoginState = { from: `${location.pathname}${location.search}`, reason: session.data.expired ? "expired" : "required" };
    return <Navigate to="/admin/login" replace state={state} />;
  }
  return <>{children}</>;
}
