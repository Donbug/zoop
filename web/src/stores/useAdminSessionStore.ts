import { create } from 'zustand';
import type { AdminSessionState } from '@/types/admin';

// 관리자 API 검증 결과만 주입한다. 회원 토큰으로 관리자 세션을 만들지 않는다.
// 새로고침 후 세션 회수 API는 추후 연결하며 현재는 로그인으로 진입한다.
export const useAdminSessionStore = create<AdminSessionState>((set) => ({
  session: null,
  setSession: (session) => set({ session }),
  clearSession: () => set({ session: null }),
}));
