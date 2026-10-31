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
import LoginFrame from '@/components/auth/LoginFrame';
import ConfirmDialog from '@/components/common/ConfirmDialog';
import SessionStatus from '@/components/auth/SessionStatus';
import { authAlert, authNote, focusRing } from '@/components/auth/authStyles';
import type { LoginLocationState } from '@/types/auth';

// 와이어프레임 D-AUT-01 버튼 문구. 서버가 알려 준 제공자만 버튼을 둔다.
const SOCIAL_LABEL: Record<string, string> = {
  google: '구글 로그인',
  kakao: '카카오톡 로그인',
};
// D-AUT-01: 승인된 중앙 로그인 시안. 셸의 3px 모서리 규칙보다 우선한다.
const pillInput = `h-12 w-full rounded-full! border-0 bg-zoop-soft px-5 text-body text-zoop-ink placeholder:text-zoop-muted focus:bg-zoop-paper focus:ring-1 focus:ring-zoop-ink disabled:opacity-60 ${focusRing}`;
const pillButton = `mt-2 flex h-12 w-full items-center justify-center rounded-full! bg-zoop-ink text-body font-bold text-zoop-paper disabled:cursor-progress disabled:opacity-60 ${focusRing}`;
const textLink = `min-h-0! rounded! bg-transparent text-zoop-muted hover:text-zoop-ink hover:underline aria-disabled:opacity-60 disabled:opacity-60 ${focusRing}`;
const startCircle = `group grid rounded-full! aria-disabled:cursor-not-allowed aria-disabled:opacity-60 ${focusRing}`;

/** 제공자 상표 색은 유지하고 aria-label로 이름을 제공한다. */
function StartIcon({ id }: { id: string }) {
  const circle =
    'grid size-10 place-items-center rounded-full transition-transform group-hover:scale-105';
  if (id === 'google')
    return (
      <span
        aria-hidden="true"
        className={`${circle} border-[0.667px] border-zoop-line bg-zoop-paper`}
      >
        <svg viewBox="0 0 48 48" className="size-5">
          <path
            fill="#EA4335"
            d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
          />
          <path
            fill="#4285F4"
            d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
          />
          <path
            fill="#FBBC05"
            d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
          />
          <path
            fill="#34A853"
            d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
          />
        </svg>
      </span>
    );
  if (id === 'kakao')
    return (
      <span aria-hidden="true" className={`${circle} bg-[#FEE500]`}>
        <svg viewBox="0 0 24 24" className="size-6">
          <path
            fill="#191919"
            d="M12 3.6c-4.97 0-9 3.13-9 7 0 2.5 1.68 4.69 4.2 5.93l-.86 3.13c-.08.28.24.5.48.34l3.73-2.47c.47.05.95.07 1.45.07 4.97 0 9-3.13 9-7s-4.03-7-9-7z"
          />
        </svg>
      </span>
    );

  return (
    <span
      aria-hidden="true"
      className={`${circle} border-[0.667px] border-zoop-line bg-zoop-paper text-body font-bold`}
    >
      {id.slice(0, 1).toUpperCase()}
    </span>
  );
}

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
  const [guestConfirm, setGuestConfirm] = useState(false);
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
        setGuestConfirm(false);
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
    <LoginFrame>
      <section className="mx-auto flex w-full max-w-[340px] flex-col gap-6 text-zoop-ink">
        <header className="mb-5 text-center">
          <p className="text-display leading-none font-[750] tracking-[-0.045em] font-heading">
            ZOOP
          </p>
          <p className="mt-4 text-body leading-6 text-zoop-muted">
            내 종목 주변의 사건을 하나의 그래프로 봐요
          </p>
        </header>
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
            className="flex flex-col gap-2.5"
          >
            <h1 id="login-title" className="sr-only">
              이메일로 로그인
            </h1>
            <label htmlFor="login-email" className="sr-only">
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
              placeholder="이메일"
              className={pillInput}
            />
            <label htmlFor="login-password" className="sr-only">
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
              placeholder="비밀번호"
              className={pillInput}
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
                className={pillButton}
                onClick={() =>
                  void flow.run(undefined, email.trim() || undefined, from)
                }
              >
                로그인 상태 다시 확인
              </button>
            ) : (
              <button type="submit" disabled={busy} className={pillButton}>
                {flow.busy ? '로그인하고 있어요' : '로그인'}
              </button>
            )}
            <div className="mt-1 flex items-center justify-between gap-2 px-2 text-caption">
              <Link
                to="/signup"
                aria-disabled={busy}
                className={textLink}
                onClick={(event) => busy && event.preventDefault()}
              >
                이메일로 회원가입
              </Link>
              <button
                type="button"
                disabled={busy}
                className={textLink}
                onClick={() => {
                  setGuestError(false);
                  setGuestConfirm(true);
                }}
              >
                {pending === 'guest'
                  ? '시작하고 있어요'
                  : '로그인 없이 둘러보기'}
              </button>
            </div>
          </form>
        )}

        <div className="flex flex-col gap-2.5">
          {providers.length > 0 && (
            <>
              <div className="flex items-center gap-3 text-caption text-zoop-faint before:h-px before:flex-1 before:bg-zoop-line after:h-px after:flex-1 after:bg-zoop-line">
                또는
              </div>
              <ul className="m-0 flex list-none justify-center gap-4 p-0">
                {providers.map((provider) => (
                  <li key={provider.id}>
                    <a
                      // 서버는 허용한 경로(/login·/signup·/)로만 돌려보낸다. 로그인 화면으로 돌아와 FS006 분기를 이어 간다.
                      href={socialLoginUrl(provider.id, '/login')}
                      aria-disabled={busy}
                      aria-label={
                        SOCIAL_LABEL[provider.id] ?? `${provider.name} 로그인`
                      }
                      className={startCircle}
                      onClick={(event) => busy && event.preventDefault()}
                    >
                      <StartIcon id={provider.id} />
                    </a>
                  </li>
                ))}
              </ul>
            </>
          )}
          {guestError && (
            <p role="alert" className={authAlert}>
              비회원으로 시작하지 못했어요. 다시 시도해 주세요.
            </p>
          )}
          <p className={`${authNote} mt-2 text-center text-zoop-muted!`}>
            본 서비스는 투자 권유를 제공하지 않아요.
          </p>
        </div>
      </section>
      {guestConfirm && (
        <ConfirmDialog
          title="로그인 없이 둘러볼까요?"
          confirmLabel={
            pending === 'guest' ? '시작하고 있어요' : '둘러보기 시작'
          }
          cancelLabel="취소"
          pending={pending === 'guest'}
          onConfirm={() => void startAsGuest()}
          onCancel={() => setGuestConfirm(false)}
        >
          <dl className="m-0 flex flex-col gap-3 text-body leading-relaxed">
            <div>
              <dt className="font-bold text-zoop-ink">바로 볼 수 있어요</dt>
              <dd className="m-0 text-zoop-muted">
                시장 전체 지도, 공개 브리핑, 기업 정보
              </dd>
            </div>
            <div>
              <dt className="font-bold text-zoop-ink">로그인이 필요해요</dt>
              <dd className="m-0 text-zoop-muted">
                관심 종목 설정, 가상 계좌 연결, 내 종목 지도, AI 질문
              </dd>
            </div>
          </dl>
          <p className={authNote}>
            둘러보다가 언제든 로그인하거나 가입하면 모든 기능을 쓸 수 있어요.
          </p>
        </ConfirmDialog>
      )}
    </LoginFrame>
  );
}
