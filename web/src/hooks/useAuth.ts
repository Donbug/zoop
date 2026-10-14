import { useEffect } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { loadSession, logout } from '@/apis/auth/auth';
import { isMemberSession } from '@/apis/auth/member-session';
export function useAuth() {
  const status = useAuthStore((s) => s.status);
  const session = useAuthStore((s) => s.session);
  const member = useAuthStore((s) => s.member);
  const onboardingCompleted = useAuthStore((s) => s.onboardingCompleted);
  useEffect(() => {
    if (status === 'checking' && !session) void loadSession().catch(() => {});
  }, [status, session]);
  return {
    status,
    checking: status === 'checking',
    failed: status === 'error',
    isAuthenticated: status === 'ready' && isMemberSession(session),
    isGuest: session?.kind === 'guest',
    member,
    onboardingCompleted,
    logout,
    retry: () => {
      void loadSession(true).catch(() => {});
    },
  };
}
