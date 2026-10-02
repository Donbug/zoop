// UI-01 시작 화면(요구 1·2·4·5): 이메일 로그인, 이메일 회원가입, 소셜 로그인, 비회원 시작 중 하나를 고른다.
// 로그인 성공 뒤 이동은 가드(RedirectIfSignedIn)가 맡는다: 설정 미완료 → 초기 설정, 완료 → 가려던 주소 또는 메인(요구 6).
// 소셜 로그인은 실제 제공자 자격 증명이 없어 BFF의 개발용 모의 제공자를 쓴다(화면에 그렇게 밝힌다).
import { Eye, LogIn, Mail, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { ApiError } from "@/api/client";
import { useGuestStart, useLogin, useSocialProviders } from "@/api/queries";
import { DisclaimerNote } from "@/components/domain/status-labels";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorState } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { returnPath } from "@/features/app-shell";
import { fieldErrorsOf } from "@/lib/labels";

// 서버에 등록된 데모 계정. 서버가 검증하므로 프론트는 입력칸 기본값으로만 쓴다.
const DEMO_EMAIL = "demo@zoop.local";
const DEMO_PASSWORD = "zoop-demo";

// 소셜 로그인 결과(BFF callback이 /login?social=로 돌려보낸다)와 차단 안내.
const notices: Record<string, string> = {
  cancelled: "소셜 로그인을 취소했어요. 다른 방법을 골라 주세요.",
  failed: "소셜 로그인을 확인하지 못했어요. 다시 시도하거나 다른 방법을 골라 주세요.",
  email_in_use: "이미 이메일로 가입된 주소예요. 이메일로 로그인해 주세요.",
  blocked: "이용이 제한된 계정이에요. 운영팀에 문의해 주세요.",
};

export function LoginPage() {
  const location = useLocation();
  const [params] = useSearchParams();
  const login = useLogin();
  const guest = useGuestStart();
  const providers = useSocialProviders();
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [guestOpen, setGuestOpen] = useState(false);
  const isDemo = email === DEMO_EMAIL && password === DEMO_PASSWORD;
  const from = returnPath(location.state);
  const notice = notices[params.get("social") ?? ""] ?? notices[params.get("notice") ?? ""];

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate({ email, password });
  };

  const fields = fieldErrorsOf(login.error);
  const credentialError = login.error instanceof ApiError && login.error.code === "invalid_credentials";
  const blocked = login.error instanceof ApiError && login.error.code === "member_blocked";
  const otherError = login.isError && !credentialError && !blocked && Object.keys(fields).length === 0;
  const busy = login.isPending || guest.isPending;

  return (
    <div className="mx-auto flex w-full max-w-sm flex-1 flex-col gap-8 px-4 pt-10 pb-8 md:justify-center md:pt-8">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold text-text-primary">줍</h1>
        <p className="text-md text-text-secondary">내 종목 주변의 사건과 근거를 탐색해요</p>
      </div>

      {(notice || blocked) && (
        <p role="alert" className="rounded-sm border border-border-strong bg-surface-sunken px-3 py-2 text-base text-text-primary">
          {blocked ? notices.blocked : notice}
        </p>
      )}

      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate aria-labelledby="login-heading">
        <h2 id="login-heading" className="text-lg font-semibold text-text-primary">
          이메일로 로그인
        </h2>
        <Input
          label="이메일"
          type="email"
          autoComplete="username"
          inputMode="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fields.email}
          required
        />
        <Input
          label="비밀번호"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fields.password ?? (credentialError ? "이메일 또는 비밀번호가 올바르지 않아요. 다시 입력해 주세요." : undefined)}
          hint={isDemo ? "데모 계정이 입력되어 있어요" : undefined}
          required
        />
        {otherError && <ErrorState error={login.error} title="로그인하지 못했어요" compact />}
        <Button type="submit" size="lg" loading={login.isPending} disabled={busy && !login.isPending}>
          <LogIn aria-hidden="true" />
          로그인
        </Button>
      </form>

      <div className="flex flex-col gap-3">
        <p className="text-sm text-text-secondary">처음이거나 다른 방법으로 시작하기</p>
        <Button asChild variant="secondary" size="lg">
          <Link to="/signup" state={location.state}>
            <Mail aria-hidden="true" />
            이메일로 회원가입
          </Link>
        </Button>
        {providers.data?.items.map((p) => (
          <div key={p.id} className="flex flex-col gap-1">
            <Button asChild variant="secondary" size="lg">
              <a href={`/api/auth/social/${encodeURIComponent(p.id)}/authorize?${new URLSearchParams({ returnTo: from ?? "/" })}`}>
                <UserRound aria-hidden="true" />
                {p.label}으로 계속
              </a>
            </Button>
            {p.development && <p className="text-sm text-text-secondary">개발용 모의 제공자예요. 실제 소셜 계정과 연결되지 않아요.</p>}
          </div>
        ))}
        {providers.isError && <ErrorState error={providers.error} title="소셜 로그인 목록을 불러오지 못했어요" onRetry={() => void providers.refetch()} compact />}
        <Button type="button" variant="ghost" size="lg" disabled={busy} onClick={() => setGuestOpen(true)}>
          <Eye aria-hidden="true" />
          로그인 없이 둘러보기
        </Button>
      </div>

      <DisclaimerNote>본 서비스는 투자 권유를 제공하지 않아요.</DisclaimerNote>

      <Dialog
        open={guestOpen}
        onOpenChange={setGuestOpen}
        title="로그인 없이 둘러볼까요?"
        closeLabel="닫기"
        footer={
          <div className="flex flex-col-reverse gap-2 md:flex-row md:justify-end">
            <Button variant="ghost" onClick={() => setGuestOpen(false)}>
              돌아가기
            </Button>
            <Button loading={guest.isPending} onClick={() => guest.mutate()}>
              둘러보기 시작
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-3 text-base text-text-primary">
          <p>시장 전체 지도와 브리핑은 바로 볼 수 있어요.</p>
          <p>가상 계좌 연결, 관심 종목, 내 종목 지도는 로그인해야 쓸 수 있어요.</p>
          {/* FS001 화면 전환 실패: 시작 화면(이 창)을 그대로 두고 안내한다. [둘러보기 시작]이 다시 시도, [돌아가기]가 시작 방식 고르기다. */}
          {guest.isError && (
            <ErrorState error={guest.error} title="화면을 불러오지 못했어요" message="둘러보기를 시작하지 못했어요. [둘러보기 시작]으로 다시 시도해 주세요." compact />
          )}
        </div>
      </Dialog>
    </div>
  );
}
