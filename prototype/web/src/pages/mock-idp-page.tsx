// 개발용 모의 소셜 로그인 제공자의 동의 화면(요구 4·70). 실제 제공자(IdP) 화면 자리를 흉내 낸다.
// BFF authorize가 state·redirect_uri를 붙여 이리로 보내고, [동의하고 계속]은 일회용 code를 받아 BFF callback으로,
// [취소]는 error=access_denied로 callback에 돌려보낸다. callback이 state를 검증한 뒤 로그인·가입하거나 시작 화면으로 돌린다.
import { FlaskConical } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { api, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { fieldErrorsOf } from "@/lib/labels";

const CALLBACK_PREFIX = "/api/auth/social/";

export function MockIdpPage() {
  const [params] = useSearchParams();
  const state = params.get("state") ?? "";
  const redirectUri = params.get("redirect_uri") ?? "";
  const valid = state.length > 0 && redirectUri.startsWith(CALLBACK_PREFIX);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const consent = async (event: FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await api<Schemas["MockIdpRedirect"]>("/api/auth/social/mock/idp/consent", {
        method: "POST",
        body: { state, redirectUri, email, displayName },
      });
      window.location.assign(result.redirectTo);
    } catch (cause) {
      setError(cause);
      setPending(false);
    }
  };
  const cancel = () => window.location.assign(`${redirectUri}?${new URLSearchParams({ error: "access_denied", state })}`);
  const fields = fieldErrorsOf(error);

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-sm flex-col justify-center gap-6 px-4 py-10">
      <div className="flex flex-col gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-warning">
          <FlaskConical className="size-4" aria-hidden="true" />
          개발용 모의 로그인
        </p>
        <h1 className="text-2xl font-bold text-text-primary">모의 소셜 계정으로 로그인</h1>
        <p className="text-base text-text-secondary">실제 소셜 서비스가 아니에요. 입력한 이메일이 모의 계정이 되고, 줍에 이메일과 이름을 전달해요.</p>
      </div>
      {!valid ? (
        <p role="alert" className="text-base font-medium text-error">
          로그인 요청이 올바르지 않아요. 줍 시작 화면에서 다시 시작해 주세요.
        </p>
      ) : (
        <form onSubmit={consent} className="flex flex-col gap-4" noValidate>
          <Input label="모의 계정 이메일" type="email" inputMode="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} error={fields.email} required />
          <Input label="이름" autoComplete="off" value={displayName} onChange={(e) => setDisplayName(e.target.value)} hint="비워 두면 이메일 앞부분을 써요" />
          {error != null && !fields.email && <ErrorState error={error} title="동의를 처리하지 못했어요" compact />}
          <Button type="submit" size="lg" loading={pending}>
            동의하고 계속
          </Button>
          <Button type="button" variant="secondary" size="lg" disabled={pending} onClick={cancel}>
            취소
          </Button>
        </form>
      )}
    </main>
  );
}
