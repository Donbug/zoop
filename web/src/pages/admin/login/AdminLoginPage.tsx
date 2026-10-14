import { useEffect, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { loadAdminSession, logInAdmin } from '@/apis/admin/auth';
import { ApiError } from '@/apis/auth/ApiService';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type {
  AdminExpiredReason,
  AdminLoginLocationState,
} from '@/types/admin';

function loginErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'INVALID_CREDENTIALS' || error.status === 401)
      return '관리자 이메일 또는 비밀번호가 맞지 않아요.';
    if (error.code === 'ACCESS_DENIED' || error.status === 403)
      return '관리자 권한이 없는 계정이에요. 권한을 확인해 주세요.';
    if (error.code === 'RATE_LIMITED' || error.status === 429)
      return '로그인 시도가 많아요. 잠시 후 다시 시도해 주세요.';
    if (error.code === 'INVALID_REQUEST' || error.status === 422)
      return '이메일과 비밀번호 형식을 확인해 주세요.';
  }
  return '로그인하지 못했어요. 잠시 후 다시 시도해 주세요.';
}

function expiredMessage(reason: AdminExpiredReason | null | undefined) {
  if (reason === 'idle')
    return '오래 활동이 없어 관리자 세션이 만료됐어요. 다시 로그인해 주세요.';
  if (reason === 'absolute')
    return '관리자 세션 최대 이용 시간이 지나 만료됐어요. 다시 로그인해 주세요.';
  return null;
}

function fromPath(state: AdminLoginLocationState | null) {
  const from = state?.from;
  if (!from?.pathname?.startsWith('/admin') || from.pathname === '/admin/login')
    return '/admin';
  return `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`;
}

// A-ADM-05c 관리자 로그인 (FS073·NFS001)
// - 회원 로그인과 별개인 관리자 세션. 회원으로 로그인해 있어도 관리자 권한을 대신하지 않는다.
// - 상태: 필수 입력 누락·인증 실패·접근 불가(권한 없음)·세션 만료·성공(→ A-ADM-01 운영 대시보드)
export default function AdminLoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const routeState = location.state as AdminLoginLocationState | null;
  const destination = fromPath(routeState);
  const status = useAdminSessionStore((state) => state.status);
  const session = useAdminSessionStore((state) => state.session);
  const admin = useAdminSessionStore((state) => state.admin);
  const setSession = useAdminSessionStore((state) => state.setSession);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [missing, setMissing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === 'checking' && session === null) void loadAdminSession();
  }, [status, session]);

  // 이미 관리자 세션이 있으면 로그인 화면을 거치지 않는다.
  useEffect(() => {
    if (admin && !pending) navigate(destination, { replace: true });
  }, [admin, pending, destination, navigate]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const trimmed = email.trim();
    if (!trimmed || !password) {
      setMissing(true);
      return;
    }
    setMissing(false);
    setError(null);
    setPending(true);
    try {
      const next = await logInAdmin({ email: trimmed, password });
      if (!next.authenticated || !next.admin) {
        setError('관리자 권한이 없는 계정이에요. 권한을 확인해 주세요.');
        setPending(false);
        return;
      }
      setSession(next);
      navigate(destination, { replace: true });
    } catch (loginError) {
      setError(loginErrorMessage(loginError));
      setPending(false);
    }
  }

  const expired = expiredMessage(
    routeState?.expiredReason ??
      (session?.expired ? session.expiredReason : null),
  );
  const idleMinutes = session?.idleTimeoutSeconds
    ? Math.round(session.idleTimeoutSeconds / 60)
    : null;

  return (
    <main
      className="grid min-h-dvh place-items-center bg-zoop-soft px-4 py-12 text-zoop-ink"
      data-screen-id="A-ADM-05c"
    >
      <section
        className="flex w-full max-w-[358px] flex-col gap-4"
        aria-labelledby="admin-login-title"
      >
        <h1
          id="admin-login-title"
          className="text-xl font-[750] tracking-[-0.035em]"
        >
          줍 관리자
        </h1>
        {expired && !error && (
          <p
            role="alert"
            className="rounded-[3px] border-[0.667px] border-dashed border-zoop-line bg-zoop-paper px-3.5 py-3 text-[11px] leading-relaxed text-zoop-ink"
          >
            {expired}
          </p>
        )}
        <form
          noValidate
          className="flex flex-col gap-2"
          onSubmit={(event) => void handleSubmit(event)}
        >
          <label
            htmlFor="admin-email"
            className="mt-2 text-[11px] font-semibold text-zoop-muted"
          >
            관리자 이메일
          </label>
          <input
            id="admin-email"
            className="h-[46px] rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-[13px] text-zoop-ink focus:border-[1.333px] focus:border-zoop-ink disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
            type="email"
            autoComplete="username"
            value={email}
            disabled={pending}
            aria-invalid={missing && !email.trim()}
            onChange={(event) => setEmail(event.target.value)}
          />
          <label
            htmlFor="admin-password"
            className="mt-2 text-[11px] font-semibold text-zoop-muted"
          >
            비밀번호
          </label>
          <input
            id="admin-password"
            className="h-[46px] rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-[13px] text-zoop-ink focus:border-[1.333px] focus:border-zoop-ink disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
            type="password"
            autoComplete="current-password"
            value={password}
            disabled={pending}
            aria-invalid={missing && !password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {missing && (
            <p
              role="alert"
              className="text-[11px] leading-relaxed text-[#b42318]"
            >
              관리자 이메일과 비밀번호를 모두 입력해 주세요.
            </p>
          )}
          {error && (
            <p
              role="alert"
              className="text-[11px] leading-relaxed text-[#b42318]"
            >
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={pending}
            className="mt-3.5 h-[46px] rounded-[3px] bg-zoop-ink text-[13px] font-bold text-zoop-paper disabled:cursor-progress disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
          >
            {pending ? '확인하고 있어요' : '관리자 로그인'}
          </button>
        </form>
        <p className="text-center text-[10px] text-zoop-faint">
          관리자 세션은 회원 세션과 분리돼요
          {idleMinutes ? ` · ${idleMinutes}분 동안 활동이 없으면 만료` : ''}
        </p>
        <Link
          to="/login"
          className="self-center text-[11px] text-zoop-muted underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
        >
          회원 로그인으로
        </Link>
      </section>
    </main>
  );
}
