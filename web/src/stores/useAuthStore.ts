import { create } from 'zustand';
import type { AuthState, Session } from '@/types/auth';

const ANONYMOUS: Session = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};

function derive(session: Session) {
  const isMember = session.kind === 'member' && session.user !== null;
  return {
    session,
    member: isMember ? session.user : null,
    onboardingCompleted: isMember ? (session.setup?.completed ?? false) : null,
  };
}

// 서버 세션(HttpOnly 쿠키)의 화면용 사본. 인증 판단의 기준은 서버이며
// 브라우저 저장소에 인증 정보를 두지 않는다.
export const useAuthStore = create<AuthState>((set) => ({
  status: 'checking',
  session: null,
  member: null,
  onboardingCompleted: null,
  setSession: (session) => set({ status: 'ready', ...derive(session) }),
  setStatus: (status) => set({ status }),
  clearSession: () => {
    sessionStorage.removeItem('oauth_state');
    set({ status: 'ready', ...derive(ANONYMOUS) });
  },
}));

/** 회원 세션이면 회원 ID, 아니면 null. 회원이 바뀌었는지 비교할 때 쓴다. */
export function selectMemberId(state: AuthState) {
  return state.member?.id ?? null;
}
