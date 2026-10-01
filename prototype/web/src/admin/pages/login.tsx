// 관리자 로그인(요구 82). 승인된 관리자 계정만. 만료로 돌아온 경우 그 이유를 한 줄로 알려 주고, 로그인 뒤 원래 화면으로 돌려보낸다.
import { CircleAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { useAdminLogin, useAdminSession } from "../api";
import type { AdminLoginState } from "../session";

/** 관리자 영역 안의 경로만 돌아갈 곳으로 받는다(열린 리다이렉트 방지). */
function safeReturnPath(from: string | undefined) {
  return from && from.startsWith("/admin") && !from.startsWith("/admin/login") ? from : "/admin";
}

export function AdminLoginPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const state = (location.state ?? {}) as AdminLoginState;
  const session = useAdminSession();
  const login = useAdminLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const returnTo = safeReturnPath(state.from);

  if (session.data?.authenticated && !login.isPending) return <Navigate to={returnTo} replace />;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate({ email, password }, { onSuccess: () => navigate(returnTo, { replace: true }) });
  };
  const credentialError = login.error instanceof ApiError && (login.error.status === 401 || login.error.status === 403);

  return (
    <main className="flex min-h-dvh items-center justify-center bg-surface-base px-4">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-baseline gap-2">
          <h1 className="text-2xl font-bold text-text-primary">줍 관리자</h1>
        </div>
        {state.reason === "expired" && !login.isSuccess && (
          <p role="status" className="flex items-center gap-2 text-base text-text-primary">
            <CircleAlert className="size-5 shrink-0 text-warning" aria-hidden="true" />
            로그인이 만료됐어요. 다시 로그인해 주세요.
          </p>
        )}
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <Input label="관리자 이메일" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <Input
            label="비밀번호"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={credentialError ? "관리자 계정 정보가 맞지 않아요. 이메일과 비밀번호를 확인해 주세요." : undefined}
            required
          />
          {login.isError && !credentialError && <ErrorState error={login.error} title="로그인하지 못했어요" compact />}
          <Button type="submit" size="lg" loading={login.isPending} disabled={!email || !password}>
            관리자 로그인
          </Button>
        </form>
      </div>
    </main>
  );
}
