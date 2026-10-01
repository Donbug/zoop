// 이메일 회원가입(요구 3): 이메일·비밀번호·표시 이름 + 필수 약관 동의.
// 필수 입력·형식·약관·이메일 중복은 서버가 판단하고(details.fields), 화면은 항목마다 그 안내를 붙인다.
// 가입하면 서버가 바로 로그인시키고, 가드가 초기 설정(/onboarding)으로 보낸다(DEC01 미결정: 자동 로그인 → 초기 설정으로 둔다).
// 약관 본문은 아직 없다. 제목만 보이고 본문 자리에는 「약관 본문 준비 중」을 둔다.
import { ArrowLeft, ChevronDown, UserPlus } from "lucide-react";
import { useId, useRef, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";
import { ApiError } from "@/api/client";
import { useSignup, useTerms } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { ErrorState, SkeletonLines } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { fieldErrorsOf } from "@/lib/labels";

export function SignupPage() {
  const location = useLocation();
  const signup = useSignup();
  const terms = useTerms();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [agreed, setAgreed] = useState<string[]>([]);
  const formRef = useRef<HTMLFormElement>(null);
  const termsErrorId = useId();

  const fields = fieldErrorsOf(signup.error);
  const otherError = signup.isError && Object.keys(fields).length === 0;
  const allIds = terms.data?.items.map((t) => t.id) ?? [];
  const allAgreed = allIds.length > 0 && allIds.every((id) => agreed.includes(id));

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    signup.mutate(
      { email, password, displayName, agreements: agreed },
      {
        // 첫 번째로 잘못된 항목으로 포커스를 옮긴다.
        onError: () => requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus()),
      },
    );
  };

  return (
    <div className="mx-auto flex w-full max-w-sm flex-1 flex-col gap-6 px-4 pt-6 pb-8 md:pt-10">
      <Button asChild variant="link" className="self-start">
        <Link to="/login" state={location.state}>
          <ArrowLeft aria-hidden="true" />
          시작 화면으로
        </Link>
      </Button>
      <h1 className="text-2xl font-bold text-text-primary">이메일로 가입하기</h1>

      <form ref={formRef} onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        <Input label="이메일" type="email" autoComplete="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} error={fields.email} required />
        <Input
          label="비밀번호"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fields.password}
          hint="영문과 숫자를 섞어 8자 이상"
          required
        />
        <Input
          label="표시 이름"
          autoComplete="nickname"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          error={fields.displayName}
          hint="화면에 보이는 이름이에요. 20자까지"
          required
        />

        <fieldset className="flex flex-col gap-1" aria-describedby={fields.agreements ? termsErrorId : undefined}>
          <legend className="pb-1 text-sm font-medium text-text-primary">약관 동의</legend>
          {terms.isPending && <SkeletonLines lines={2} label="약관을 불러오고 있어요" />}
          {terms.isError && <ErrorState error={terms.error} title="약관을 불러오지 못했어요" onRetry={() => void terms.refetch()} compact />}
          {terms.data && (
            <>
              <label className="flex min-h-11 items-center gap-3 border-b border-border-subtle text-base font-semibold text-text-primary">
                <input
                  type="checkbox"
                  className="size-5 accent-brand-primary"
                  checked={allAgreed}
                  onChange={(e) => setAgreed(e.target.checked ? allIds : [])}
                />
                모두 동의
              </label>
              {terms.data.items.map((term) => (
                <div key={term.id} className="flex flex-col">
                  <label className="flex min-h-11 items-center gap-3 text-base text-text-primary">
                    <input
                      type="checkbox"
                      className="size-5 accent-brand-primary"
                      checked={agreed.includes(term.id)}
                      onChange={(e) => setAgreed((prev) => (e.target.checked ? [...prev.filter((x) => x !== term.id), term.id] : prev.filter((x) => x !== term.id)))}
                      aria-invalid={fields.agreements && term.required && !agreed.includes(term.id) ? true : undefined}
                    />
                    <span>
                      {term.title} <span className="text-text-secondary">({term.required ? "필수" : "선택"})</span>
                    </span>
                  </label>
                  <details className="group pb-1 pl-8">
                    <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1 text-sm text-text-secondary [&::-webkit-details-marker]:hidden">
                      본문 보기
                      <ChevronDown className="size-4 transition-token group-open:rotate-180" aria-hidden="true" />
                    </summary>
                    <p className="text-sm text-text-secondary">약관 본문 준비 중</p>
                  </details>
                </div>
              ))}
            </>
          )}
          {fields.agreements && (
            <p id={termsErrorId} className="text-sm font-medium text-error">
              {fields.agreements}
            </p>
          )}
        </fieldset>

        {otherError && <ErrorState error={signup.error} title="가입하지 못했어요" compact />}
        {signup.error instanceof ApiError && (signup.error.code === "email_taken" || signup.error.details?.emailTaken === true) && (
          <Button asChild variant="link" className="self-start">
            <Link to="/login" state={location.state}>
              이 이메일로 로그인하기
            </Link>
          </Button>
        )}
        <Button type="submit" size="lg" loading={signup.isPending}>
          <UserPlus aria-hidden="true" />
          가입하고 시작하기
        </Button>
      </form>
    </div>
  );
}
