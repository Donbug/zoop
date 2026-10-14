import { create } from 'zustand';
import type { AuthState, Session } from '@/types/auth';
import { useOnboardingStore } from './useOnboardingStore';
import { useGraphUiStore } from './useGraphUiStore';
import { useAiChatStore } from './useAiChatStore';

function resetPrivateState() {
  useOnboardingStore.getState().reset();
  useGraphUiStore.getState().reset();
  useAiChatStore.getState().reset();
  try {
    sessionStorage.removeItem('zoop.graph.personal-filter');
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
    if (get().member?.id !== member?.id) resetPrivateState();
    set((state) => ({
      session,
      status: 'ready',
      member,
      onboardingCompleted: member ? (session.setup?.completed ?? false) : null,
      sessionRevision: state.sessionRevision + 1,
    }));
  },
  clearSession: () => {
    resetPrivateState();
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
