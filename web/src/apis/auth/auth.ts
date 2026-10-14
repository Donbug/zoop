import { useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { getSession, logOut } from './session';

let loading: Promise<void> | null = null;

/** 서버 세션을 읽어 화면 상태에 반영한다. 동시에 여러 번 불러도 요청은 하나다. */
export function loadSession() {
  if (!loading) {
    useAuthStore.getState().setStatus('checking');
    loading = getSession()
      .then(
        (session) => useAuthStore.getState().setSession(session),
        () => useAuthStore.getState().setStatus('error'),
      )
      .finally(() => {
        loading = null;
      });
  }
  return loading;
}

/**
 * 지금 세션의 CSRF 토큰. 서버가 세션 응답(SessionResponse.csrfToken)으로 내려 준 값이며
 * 브라우저 저장소에 따로 두지 않는다. 공통 call()은 쓰기 요청에 이 값을 자동으로 붙인다.
 */
export function getCsrfToken() {
  return useAuthStore.getState().session?.csrfToken ?? null;
}

/** 화면에 남은 회원별 상태를 비운다(서버 세션은 건드리지 않는다). */
export function clearAuthentication() {
  useAuthStore.getState().clearSession();
  useOnboardingStore.getState().reset();
  useGraphUiStore.getState().reset();
  useAiChatStore.getState().reset();
}

/** 서버 세션을 폐기하고 화면 상태를 비운다. 요청이 실패해도 화면은 로그아웃 상태로 둔다. */
export async function logout() {
  try {
    await logOut();
  } finally {
    clearAuthentication();
  }
}

export function isMember() {
  return useAuthStore.getState().member !== null;
}
