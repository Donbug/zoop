import { useAuthStore } from '@/stores/useAuthStore';
import { logOut } from './session';
export { loadSession } from './member-session';
export const clearAuthentication = () => useAuthStore.getState().clearSession();
/**
 * 지금 세션의 CSRF 토큰. 서버가 세션 응답(SessionResponse.csrfToken)으로 내려 준 값이며
 * 브라우저 저장소에 따로 두지 않는다. 공통 call()은 쓰기 요청에 이 값을 자동으로 붙인다.
 */
export function getCsrfToken() {
  return useAuthStore.getState().session?.csrfToken ?? null;
}
export function isMember() {
  const state = useAuthStore.getState();
  return (
    state.status === 'ready' &&
    state.session?.authenticated === true &&
    state.session.kind === 'member' &&
    state.member !== null
  );
}
export async function logout() {
  const revision = useAuthStore.getState().sessionRevision;
  try {
    await logOut();
  } finally {
    if (revision === useAuthStore.getState().sessionRevision)
      clearAuthentication();
  }
}
