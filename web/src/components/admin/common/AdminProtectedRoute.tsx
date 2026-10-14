import { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { loadAdminSession } from '@/apis/admin/auth';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminLoginLocationState } from '@/types/admin';

/** 다음 만료 시각(유휴·최대 중 이른 쪽)까지 남은 밀리초 */
function msUntilExpiry(expiresAt: string | null, idleExpiresAt: string | null) {
  const times = [expiresAt, idleExpiresAt]
    .filter((value): value is string => Boolean(value))
    .map((value) => Date.parse(value))
    .filter((value) => !Number.isNaN(value));
  if (times.length === 0) return null;
  // setTimeout은 약 24.8일(2^31-1ms)을 넘으면 즉시 실행되므로 상한을 둔다.
  return Math.min(MAX_TIMER_MS, Math.max(0, Math.min(...times) - Date.now()));
}

const MAX_TIMER_MS = 2_147_483_647;

// A-ADM-05c 관리자 전용 라우트(FS073).
// 서버가 확인한 관리자 세션만 통과시키고, 회원 세션으로는 들어갈 수 없다.
// 만료 시각이 되면 서버에 다시 확인하고, 만료됐으면 사유와 함께 관리자 로그인으로 보낸다.
export default function AdminProtectedRoute() {
  const location = useLocation();
  const status = useAdminSessionStore((state) => state.status);
  const session = useAdminSessionStore((state) => state.session);
  const admin = useAdminSessionStore((state) => state.admin);

  useEffect(() => {
    if (status === 'checking' && session === null) void loadAdminSession();
  }, [status, session]);

  const expiresAt = session?.expiresAt ?? null;
  const idleExpiresAt = session?.idleExpiresAt ?? null;
  useEffect(() => {
    if (!admin) return;
    const wait = msUntilExpiry(expiresAt, idleExpiresAt);
    if (wait === null) return;
    const timer = window.setTimeout(() => void loadAdminSession(), wait);
    return () => window.clearTimeout(timer);
  }, [admin, expiresAt, idleExpiresAt]);

  if (status === 'checking') {
    return (
      <p role="status" className="p-6 text-xs text-zoop-muted">
        관리자 세션을 확인하고 있어요
      </p>
    );
  }

  // 확인 실패를 로그아웃으로 보지 않는다.
  if (status === 'error') {
    return (
      <div
        role="alert"
        className="flex items-center gap-3 p-6 text-xs text-zoop-muted"
      >
        <p>관리자 세션을 확인하지 못했어요.</p>
        <button
          type="button"
          onClick={() => void loadAdminSession()}
          className="h-8 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-xs font-semibold text-zoop-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
        >
          다시 시도
        </button>
      </div>
    );
  }

  if (!admin) {
    const state: AdminLoginLocationState = {
      from: location,
      expiredReason: session?.expired ? session.expiredReason : null,
    };
    return <Navigate to="/admin/login" replace state={state} />;
  }

  return <Outlet />;
}
