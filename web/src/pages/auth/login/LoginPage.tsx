import { useEffect, useState, type FormEvent } from 'react';
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
import type { LoginLocationState, Session } from '@/types/auth';

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
  if (!from?.pathname || from.pathname === '/login') return null;
  return `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`;
}

/** FS002·FS006: 초기 설정을 마쳤으면 원래 가려던 곳 또는 내 종목 지도, 아니면 초기 설정 */
function destinationAfterLogin(session: Session, from: string | null) {
  if (!session.setup?.completed) return '/onboarding';
  return from ?? '/?mode=personal';
}

// D-AUT-01 시작·이메일 로그인 (FS001·FS002·FS005·FS006)
export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = fromPath(location.state as LoginLocationState | null);
  const { checking, isAuthenticated, onboardingCompleted } = useAuth();
  const setSession = useAuthStore((state) => state.setSession);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [missing, setMissing] = useState(false);
  const [pending, setPending] = useState<'login' | 'guest' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guestError, setGuestError] = useState(false);

  // 이미 회원 세션이 있으면 로그인 화면을 거치지 않는다.
  useEffect(() => {
    if (checking || !isAuthenticated || pending) return;
    navigate(
      onboardingCompleted ? (from ?? '/?mode=personal') : '/onboarding',
      { replace: true },
    );
  }, [checking, isAuthenticated, onboardingCompleted, pending, from, navigate]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      setMissing(true);
      return;
    }
    setMissing(false);
    setError(null);
    setPending('login');
    try {
      const session = await logIn({ email: trimmedEmail, password });
      setSession(session);
      navigate(destinationAfterLogin(session, from), { replace: true });
    } catch (loginError) {
      setError(loginErrorMessage(loginError));
      setPending(null);
    }
  }

  async function startAsGuest() {
    if (pending) return;
    setGuestError(false);
    setPending('guest');
    try {
      setSession(await startGuestSession());
      // FS005: 개인 설정 없이 시장 전체 지도로 시작한다.
      navigate('/?mode=all', { replace: true });
    } catch {
      setGuestError(true);
      setPending(null);
    }
  }

  const busy = pending !== null;
  const secondaryButton =
    'flex w-full items-center justify-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-3 font-semibold text-gray-950 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <main className="flex min-h-dvh justify-center px-4 py-16">
      <section className="flex w-full max-w-md flex-col gap-6">
        <div>
          <p className="text-3xl font-bold text-gray-950">줍</p>
          <p className="mt-2 text-sm text-gray-600">
            내 종목 주변의 사건과 근거를 탐색해요
          </p>
        </div>

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
          {error && (
            <p role="alert" className="text-sm text-red-700">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="mt-1 w-full rounded-lg bg-gray-950 px-4 py-3 font-semibold text-white hover:bg-gray-800 disabled:cursor-progress disabled:bg-gray-500"
          >
            {pending === 'login' ? '로그인하고 있어요' : '로그인'}
          </button>
        </form>

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
    </main>
  );
}
