import { create } from 'zustand';
import type { AuthState, Session } from '@/types/auth';
import { useOnboardingStore } from './useOnboardingStore';
import { useGraphUiStore } from './useGraphUiStore';
import { useAiChatStore } from './useAiChatStore';

// 내 종목·지도 필터는 이 탭에서 고른 회원(OWNER_KEY)에게만 속한다.
const OWNER_KEY = 'zoop.private.owner';
const FILTER_KEYS = [
  'zoop.graph.personal-filter',
  'zoop.stocks.personal-filter',
];

/**
 * 회원이 바뀌면 개인 상태를 비운다.
 * 새로 고침 뒤 같은 회원의 세션을 복원할 때(restoring)만 그 회원이 고른 필터를 남긴다.
 */
function resetPrivateState(nextMemberId: string | null, restoring = false) {
  useOnboardingStore.getState().reset();
  useGraphUiStore.getState().reset();
  useAiChatStore.getState().reset();
  try {
    const sameOwner =
      restoring &&
      nextMemberId !== null &&
      sessionStorage.getItem(OWNER_KEY) === nextMemberId;
    if (!sameOwner)
      for (const key of FILTER_KEYS) sessionStorage.removeItem(key);
    if (nextMemberId) sessionStorage.setItem(OWNER_KEY, nextMemberId);
    else sessionStorage.removeItem(OWNER_KEY);
    sessionStorage.removeItem('oauth_state');
  } catch {
    /* cookie sessions work without browser storage */
  }
}
export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'checking',
  session: null,
  member: null,
  onboardingCompleted: null,
  sessionRevision: 0,
  setStatus: (status) => set({ status }),
  setSession: (session: Session) => {
    const member =
      session.authenticated && session.kind === 'member' ? session.user : null;
    const previous = get();
    if (previous.member?.id !== member?.id)
      resetPrivateState(
        member?.id ?? null,
        // 첫 세션 확인(checking)에서 회원을 처음 채우는 경우다.
        previous.status === 'checking' && previous.member === null,
      );
    set((state) => ({
      session,
      status: 'ready',
      member,
      onboardingCompleted: member ? (session.setup?.completed ?? false) : null,
      sessionRevision: state.sessionRevision + 1,
    }));
  },
  clearSession: () => {
    resetPrivateState(null);
    set((state) => ({
      session: null,
      status: 'ready',
      member: null,
      onboardingCompleted: null,
      sessionRevision: state.sessionRevision + 1,
    }));
  },
}));
export const selectMemberId = (state: AuthState) => state.member?.id ?? null;
