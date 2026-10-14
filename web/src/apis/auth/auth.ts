import { ACCESS_TOKEN_KEY, useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import { useAiChatStore } from '@/stores/useAiChatStore';

export { ACCESS_TOKEN_KEY } from '@/stores/useAuthStore';
export const CSRF_TOKEN_KEY = 'csrfToken';

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setAccessToken(token: string) {
  useAuthStore.getState().setAccessToken(token);
}

export function getCsrfToken() {
  return sessionStorage.getItem(CSRF_TOKEN_KEY);
}

export function setCsrfToken(token: string) {
  sessionStorage.setItem(CSRF_TOKEN_KEY, token);
}

export function clearAuthentication() {
  useAuthStore.getState().clearSession();
  useOnboardingStore.getState().reset();
  useGraphUiStore.getState().reset();
  useAiChatStore.getState().reset();
}

export function isAuthenticated() {
  return Boolean(getAccessToken());
}
