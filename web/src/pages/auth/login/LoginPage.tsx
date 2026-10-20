import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ApiError } from '@/apis/auth/ApiService';
import {
  listSocialProviders,
  logIn,
  socialLoginUrl,
  startGuestSession,
  type SocialProvider,
} from '@/apis/auth/session';
import { useAuth } from '@/hooks/useAuth';
import { useAuthStore } from '@/stores/useAuthStore';
import { useAuthCompletion } from '@/hooks/useAuthCompletion';
import { acceptMemberSession, loadSession } from '@/apis/auth/member-session';
import AuthFrame from '@/components/auth/AuthFrame';
import SessionStatus from '@/components/auth/SessionStatus';
import {
  authAlert,
  authInput,
  authLabel,
  authNote,
  authPrimaryButton,
  authSecondaryButton,
} from '@/components/auth/authStyles';
import type { LoginLocationState } from '@/types/auth';

// 와이어프레임 D-AUT-01 버튼 문구. 서버가 알려 준 제공자만 버튼을 둔다.
const SOCIAL_LABEL: Record<string, string> = {
  google: '구글 로그인',
  kakao: '카카오톡 로그인',
};

/** 소셜 인증 콜백이 /login?social=... 로 돌려준 결과 안내 */
function socialResultMessage(result: string | null) {
  if (result === 'cancelled') return '소셜 로그인을 취소했어요.';
  if (result === 'email_required')
    return '소셜 계정에서 확인된 이메일을 받지 못했어요. 이메일 제공에 동의한 뒤 다시 시도해 주세요.';
  if (result === 'link_required')
    return '이미 이메일로 가입한 계정이에요. 이메일로 로그인한 뒤 내 정보에서 소셜 계정을 연결해 주세요.';
  if (result === 'failed')
    return '소셜 로그인을 완료하지 못했어요. 잠시 후 다시 시도해 주세요.';
  return null;
}

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
  // 서버에 설정된 소셜 제공자. 불러오기 전·실패 시에는 소셜 버튼을 두지 않는다.
  const [providers, setProviders] = useState<SocialProvider[]>([]);
  const params = new URLSearchParams(location.search);
  const socialResult =
    params.get('notice') === 'blocked'
      ? '이용이 제한된 계정이라 로그아웃했어요. 고객센터로 문의해 주세요.'
      : socialResultMessage(params.get('social'));
  useEffect(() => {
    let alive = true;
    listSocialProviders().then(
      (items) => {
        if (alive) setProviders(items);
      },
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, []);

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
  return (
    <AuthFrame screen="D-AUT-01">
      <section className="flex w-full max-w-[400px] flex-col gap-6 text-zoop-ink">
        <div>
          <p className="text-[28px] font-[750] tracking-[-0.045em]">줍</p>
          <p className="mt-1.5 text-xs text-zoop-muted">
            내 종목 주변의 사건과 근거를 탐색해요
          </p>
        </div>

        {socialResult && (
          <p role="alert" className={authAlert}>
            {socialResult}
          </p>
        )}

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
            className="flex flex-col gap-1"
          >
            <h1 id="login-title" className="mb-3 text-sm font-bold">
              이메일로 로그인
            </h1>
            <label htmlFor="login-email" className={authLabel}>
              이메일
            </label>
            <input
              id="login-email"
              type="email"
              name="email"
              autoComplete="email"
              value={email}
              disabled={busy}
              aria-invalid={missing && !email.trim()}
              onChange={(event) => setEmail(event.target.value)}
              className={authInput}
            />
            <label htmlFor="login-password" className={authLabel}>
              비밀번호
            </label>
            <input
              id="login-password"
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              disabled={busy}
              aria-invalid={missing && !password}
              onChange={(event) => setPassword(event.target.value)}
              className={authInput}
            />
            {missing && (
              <p role="alert" className={authAlert}>
                이메일과 비밀번호를 모두 입력해 주세요.
              </p>
            )}
            {shownError && (
              <p role="alert" className={authAlert}>
                {shownError}
              </p>
            )}
            {flow.recovering ? (
              <button
                type="button"
                disabled={flow.busy}
                className={authPrimaryButton}
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
                className={authPrimaryButton}
              >
                {flow.busy ? '로그인하고 있어요' : '로그인'}
              </button>
            )}
          </form>
        )}

        <div className="flex flex-col gap-2.5">
          <p className="text-[11px] text-zoop-muted">
            처음이거나 다른 방법으로 시작하기
          </p>
          <Link
            to="/signup"
            aria-disabled={busy}
            className={authSecondaryButton}
            onClick={(event) => busy && event.preventDefault()}
          >
            이메일로 회원가입
          </Link>
          {providers.map((provider) => (
            <a
              key={provider.id}
              // 서버는 허용한 경로(/login·/signup·/)로만 돌려보낸다. 로그인 화면으로 돌아와 FS006 분기를 이어 간다.
              href={socialLoginUrl(provider.id, '/login')}
              aria-disabled={busy}
              className={authSecondaryButton}
              onClick={(event) => busy && event.preventDefault()}
            >
              {SOCIAL_LABEL[provider.id] ?? `${provider.name} 로그인`}
            </a>
          ))}
          <button
            type="button"
            disabled={busy}
            onClick={() => void startAsGuest()}
            className={authSecondaryButton}
          >
            {pending === 'guest' ? '시작하고 있어요' : '로그인 없이 둘러보기'}
          </button>
          {guestError && (
            <p role="alert" className={authAlert}>
              비회원으로 시작하지 못했어요. 다시 시도해 주세요.
            </p>
          )}
          <p className={authNote}>
            로그인 없이도 시장 전체 지도와 공개 브리핑을 볼 수 있어요. 계좌
            연결·관심 종목·AI 질문은 로그인 후 이용할 수 있어요.
          </p>
          <p className={authNote}>본 서비스는 투자 권유를 제공하지 않아요.</p>
        </div>
      </section>
    </AuthFrame>
  );
}
