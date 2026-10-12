import { ACCESS_TOKEN_KEY, useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import { useAiChatStore } from '@/stores/useAiChatStore';

export { ACCESS_TOKEN_KEY } from '@/stores/useAuthStore';

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setAccessToken(token: string) {
  useAuthStore.getState().setAccessToken(token);
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
