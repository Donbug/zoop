import { useEffect } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { loadSession, logout } from '@/apis/auth/auth';

/** 세션 상태. 아직 확인하지 않았으면 서버 세션을 한 번 읽는다. */
export function useAuth() {
  const status = useAuthStore((state) => state.status);
  const session = useAuthStore((state) => state.session);
  const member = useAuthStore((state) => state.member);
  const onboardingCompleted = useAuthStore(
    (state) => state.onboardingCompleted,
  );

  useEffect(() => {
    if (status === 'checking' && session === null) void loadSession();
  }, [status, session]);

  return {
    /** 세션 확인 중(처음 열었을 때) */
    checking: status === 'checking',
    /** 세션 확인 실패. 다시 시도는 retry */
    failed: status === 'error',
    retry: loadSession,
    isAuthenticated: member !== null,
    isGuest: session?.kind === 'guest',
    member,
    onboardingCompleted,
    logout,
  };
}
