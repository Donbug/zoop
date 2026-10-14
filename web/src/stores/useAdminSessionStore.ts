import { create } from 'zustand';
import type { AdminSessionState } from '@/types/admin';

// 관리자 서버 세션(zoop_admin_session)의 화면용 사본. 회원 세션(useAuthStore)과 섞지 않는다.
export const useAdminSessionStore = create<AdminSessionState>((set) => ({
  status: 'checking',
  session: null,
  admin: null,
  revision: 0,
  setSession: (session) =>
    set((state) => ({
      status: 'ready',
      session,
      admin: session.authenticated && !session.expired ? session.admin : null,
      revision: state.revision + 1,
    })),
  setStatus: (status) => set({ status }),
  clearSession: () =>
    set((state) => ({
      status: 'ready',
      session: null,
      admin: null,
      revision: state.revision + 1,
    })),
}));
