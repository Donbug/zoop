import { ApiError, call } from '@/apis/auth/ApiService';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminLoginRequest, AdminSession } from '@/types/admin';

// A-ADM-05c 관리자 인증 API (docs/api/openapi.yaml). 응답은 래퍼 없는 AdminSession이다.
// 관리자 요청은 skipAuth로 보내 관리자 401이 회원 세션을 지우지 않게 하고,
// 쓰기 요청에는 회원이 아닌 관리자 세션의 CSRF 토큰을 붙인다.

const ADMIN_AUTH = '/api/v1/admin/auth';

export function getAdminSession() {
  return call<AdminSession>(`${ADMIN_AUTH}/session`, 'GET', undefined, {
    skipAuth: true,
    skipMemberCsrf: true,
  });
}

export function logInAdmin(request: AdminLoginRequest) {
  return call<AdminSession>(`${ADMIN_AUTH}/login`, 'POST', request, {
    skipAuth: true,
    skipMemberCsrf: true,
  });
}

/**
 * 관리자 API 공통 호출. 관리자 CSRF를 붙이고, 401이면 관리자 세션만 비운다(회원 세션은 그대로).
 * 이후 관리자 화면(A-ADM-01~05b)이 이 함수를 쓴다.
 */
export async function adminCall<TResponse = unknown>(
  api: string,
  method: string,
  request?: unknown,
) {
  const state = useAdminSessionStore.getState();
  const revision = state.revision;
  const csrfToken = state.session?.csrfToken;
  try {
    return await call<TResponse>(api, method, request, {
      skipAuth: true,
      skipMemberCsrf: true,
      headers:
        csrfToken && method.toUpperCase() !== 'GET'
          ? { 'X-CSRF-Token': csrfToken }
          : undefined,
    });
  } catch (error) {
    if (
      error instanceof ApiError &&
      error.status === 401 &&
      revision === useAdminSessionStore.getState().revision
    ) {
      useAdminSessionStore.getState().clearSession();
    }
    throw error;
  }
}

/** 관리자 세션만 폐기한다. 세션이 없어도 204다. */
export function logOutAdmin() {
  return adminCall<void>(`${ADMIN_AUTH}/logout`, 'POST');
}

let loading: { revision: number; promise: Promise<void> } | null = null;

/** 서버의 관리자 세션을 읽어 반영한다. 읽는 사이 세션이 바뀌면 늦은 응답은 버린다. */
export function loadAdminSession() {
  const store = useAdminSessionStore.getState();
  if (loading?.revision === store.revision) return loading.promise;
  const revision = store.revision;
  store.setStatus('checking');
  const promise = getAdminSession()
    .then(
      (session) => {
        if (useAdminSessionStore.getState().revision === revision)
          useAdminSessionStore.getState().setSession(session);
      },
      () => {
        if (useAdminSessionStore.getState().revision === revision)
          useAdminSessionStore.getState().setStatus('error');
      },
    )
    .finally(() => {
      if (loading?.promise === promise) loading = null;
    });
  loading = { revision, promise };
  return promise;
}

/** 서버 세션을 폐기하고 화면의 관리자 상태를 비운다. 요청이 실패해도 화면은 로그아웃한다. */
export async function logoutAdmin() {
  try {
    await logOutAdmin();
  } finally {
    useAdminSessionStore.getState().clearSession();
  }
}
