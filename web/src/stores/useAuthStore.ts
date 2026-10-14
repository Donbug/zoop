import { create } from 'zustand';
import type { AuthState } from '@/types/auth';

export const ACCESS_TOKEN_KEY = 'accessToken';

// 기존 API 래퍼와 동일한 저장소 키를 사용한다. 서버 인증을 대체하지 않는다.
export const useAuthStore = create<AuthState>((set) => ({
  accessToken: localStorage.getItem(ACCESS_TOKEN_KEY),
  member: null,
  onboardingCompleted: null,
  setAccessToken: (accessToken) => {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    set({ accessToken });
  },
  setMember: (member, onboardingCompleted) =>
    set({ member, onboardingCompleted }),
  clearSession: () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    sessionStorage.removeItem('oauth_state');
    sessionStorage.removeItem('csrfToken');
    set({ accessToken: null, member: null, onboardingCompleted: null });
  },
}));
