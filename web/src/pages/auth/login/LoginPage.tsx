import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ApiError } from '@/apis/auth/ApiService';
import {
  logIn,
  socialLoginUrl,
  startGuestSession,
  type SocialProviderId,
} from '@/apis/auth/session';
import { useAuth } from '@/hooks/useAuth';
import { useAuthStore } from '@/stores/useAuthStore';
import { useAuthCompletion } from '@/hooks/useAuthCompletion';
import { acceptMemberSession, loadSession } from '@/apis/auth/member-session';
import AuthFrame from '@/components/auth/AuthFrame';
import SessionStatus from '@/components/auth/SessionStatus';
import type { LoginLocationState } from '@/types/auth';

const SOCIAL: { id: SocialProviderId; label: string }[] = [
  { id: 'google', label: '구글 로그인' },
  { id: 'kakao', label: '카카오톡 로그인' },
];

function loginErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'INVALID_CREDENTIALS' || error.status === 401)
      return '이메일 또는 비밀번호가 맞지 않아요. 다시 확인해 주세요.';
    if (error.code === 'MEMBER_BLOCKED')
      return '이용이 제한된 계정이에요. 고객센터로 문의해 주세요.';
    if (error.code === 'RATE_LIMITED' || error.status === 429)
      return '로그인 시도가 많아요. 잠시 후 다시 시도해 주세요.';
    if (error.code === 'INVALID_REQUEST' || error.status === 422)
      return '이메일과 비밀번호 형식을 확인해 주세요.';
  }
  return '로그인하지 못했어요. 잠시 후 다시 시도해 주세요.';
}

function fromPath(state: LoginLocationState | null) {
  const from = state?.from;
  if (
    !from?.pathname?.startsWith('/') ||
    from.pathname.startsWith('//') ||
    ['/login', '/signup'].includes(from.pathname)
  )
    return null;
  return `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`;
}

// D-AUT-01 시작·이메일 로그인 (FS001·FS002·FS005·FS006)
export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = fromPath(location.state as LoginLocationState | null);
  const auth = useAuth();
  const flow = useAuthCompletion();
  const active = useRef(true);
  const autoStarted = useRef(false);
  const [started, setStarted] = useState(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [missing, setMissing] = useState(false);
  const [pending, setPending] = useState<'login' | 'guest' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guestError, setGuestError] = useState(false);

  // FS006: existing members use the same confirmed holdings/interests branch.
  useEffect(() => {
    if (
      auth.status !== 'ready' ||
      !auth.isAuthenticated ||
      started ||
      autoStarted.current
    )
      return;
    autoStarted.current = true;
    setStarted(true);
    void flow.run(undefined, undefined, from);
  }, [auth.status, auth.isAuthenticated, started, flow, from]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      setMissing(true);
      return;
    }
    setMissing(false);
    setError(null);
    setStarted(true);
    await flow.run(
      () => logIn({ email: trimmedEmail, password }),
      trimmedEmail,
      from,
    );
  }

  async function startAsGuest() {
    if (busy) return;
    setGuestError(false);
    setPending('guest');
    const revision = useAuthStore.getState().sessionRevision;
    try {
      const response = await startGuestSession();
      if (
        !active.current ||
        revision !== useAuthStore.getState().sessionRevision
      )
        return;
      acceptMemberSession(response);
      const confirmed = await loadSession(true);
      if (!active.current) return;
      if (!confirmed?.authenticated || confirmed.kind !== 'guest')
        throw new Error('GUEST_SESSION_REQUIRED');
      // FS005: 개인 설정 없이 시장 전체 지도로 시작한다.
      navigate('/?mode=all', { replace: true });
    } catch {
      if (active.current) {
        setGuestError(true);
        setPending(null);
      }
    }
  }

  const busy =
    pending !== null || flow.busy || flow.recovering || auth.checking;
  const shownError =
    error ??
    (flow.recovering
      ? flow.error
      : flow.error
        ? loginErrorMessage(new ApiError(0, flow.error, flow.error))
        : null);
  const secondaryButton =
    'flex w-full items-center justify-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-3 font-semibold text-gray-950 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <AuthFrame screen="D-AUT-01">
      <section className="flex w-full max-w-md flex-col gap-6">
        <div>
          <p className="text-3xl font-bold text-gray-950">줍</p>
          <p className="mt-2 text-sm text-gray-600">
            내 종목 주변의 사건과 근거를 탐색해요
          </p>
        </div>

        {/* 세션 확인이 실패해도 로그인은 할 수 있게 안내와 폼을 함께 보여 준다.
            폼을 가리는 것은 경합이 생기는 확인 중일 때뿐이다. */}
        {auth.status === 'error' && !started && <SessionStatus />}
        {auth.status === 'checking' && !started ? (
          <SessionStatus />
        ) : (
          <form
            noValidate
            aria-labelledby="login-title"
            onSubmit={(event) => void handleSubmit(event)}
            className="flex flex-col gap-3"
          >
            <h1 id="login-title" className="font-semibold text-gray-950">
              이메일로 로그인
            </h1>
            <label className="flex flex-col gap-1 text-sm font-medium text-gray-700">
              이메일
              <input
                type="email"
                name="email"
                autoComplete="email"
                value={email}
                disabled={busy}
                aria-invalid={missing && !email.trim()}
                onChange={(event) => setEmail(event.target.value)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-3 text-base font-normal text-gray-950"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm font-medium text-gray-700">
              비밀번호
              <input
                type="password"
                name="password"
                autoComplete="current-password"
                value={password}
                disabled={busy}
                aria-invalid={missing && !password}
                onChange={(event) => setPassword(event.target.value)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-3 text-base font-normal text-gray-950"
              />
            </label>
            {missing && (
              <p role="alert" className="text-sm text-red-700">
                이메일과 비밀번호를 모두 입력해 주세요.
              </p>
            )}
            {shownError && (
              <p role="alert" className="text-sm text-red-700">
                {shownError}
              </p>
            )}
            {flow.recovering ? (
              <button
                type="button"
                disabled={flow.busy}
                className="mt-1 w-full rounded-lg bg-gray-950 px-4 py-3 font-semibold text-white hover:bg-gray-800 disabled:cursor-progress disabled:bg-gray-500"
                onClick={() =>
                  void flow.run(undefined, email.trim() || undefined, from)
                }
              >
                로그인 상태 다시 확인
              </button>
            ) : (
              <button
                type="submit"
                disabled={busy}
                className="mt-1 w-full rounded-lg bg-gray-950 px-4 py-3 font-semibold text-white hover:bg-gray-800 disabled:cursor-progress disabled:bg-gray-500"
              >
                {flow.busy ? '로그인하고 있어요' : '로그인'}
              </button>
            )}
          </form>
        )}

        <div className="flex flex-col gap-3">
          <p className="text-sm text-gray-600">
            처음이거나 다른 방법으로 시작하기
          </p>
          <Link
            to="/signup"
            aria-disabled={busy}
            className={secondaryButton}
            onClick={(event) => busy && event.preventDefault()}
          >
            이메일로 회원가입
          </Link>
          {SOCIAL.map((provider) => (
            <a
              key={provider.id}
              href={socialLoginUrl(provider.id, from ?? '/')}
              aria-disabled={busy}
              className={secondaryButton}
              onClick={(event) => busy && event.preventDefault()}
            >
              {provider.label}
            </a>
          ))}
          <button
            type="button"
            disabled={busy}
            onClick={() => void startAsGuest()}
            className={secondaryButton}
          >
            {pending === 'guest' ? '시작하고 있어요' : '로그인 없이 둘러보기'}
          </button>
          {guestError && (
            <p role="alert" className="text-sm text-red-700">
              비회원으로 시작하지 못했어요. 다시 시도해 주세요.
            </p>
          )}
          <p className="text-xs text-gray-500">
            로그인 없이도 시장 전체 지도와 공개 브리핑을 볼 수 있어요. 계좌
            연결·관심 종목·AI 질문은 로그인 후 이용할 수 있어요.
          </p>
          <p className="text-xs text-gray-500">
            본 서비스는 투자 권유를 제공하지 않아요.
          </p>
        </div>
      </section>
    </AuthFrame>
  );
}
