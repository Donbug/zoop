import { API_BASE_URL } from './api-config';
import { useAuthStore } from '@/stores/useAuthStore';

// 목표 계약(docs/api/openapi.yaml)의 인증: HttpOnly 세션 쿠키(zoop_session)와
// 세션에 결합된 X-CSRF-Token. 브라우저는 토큰을 저장하지 않고 쿠키를 그대로 보낸다.

type CallOptions = {
  /** 공개 API. 401을 받아도 세션 만료로 처리하지 않는다. */
  skipAuth?: boolean;
  /** 관리자·공개 쓰기처럼 회원 세션과 분리된 요청에는 회원 CSRF를 보내지 않는다. */
  skipMemberCsrf?: boolean;
  /** 요청별 추가 헤더(예: 목표 계약의 Idempotency-Key) */
  headers?: Record<string, string>;
  /** 페이지를 닫는 중에도 요청을 끝까지 보낸다(예: 사용 이벤트 전송) */
  keepalive?: boolean;
};

type ErrorBody = {
  error?: {
    code?: unknown;
    message?: unknown;
    retryable?: unknown;
  };
};

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

// 로그인·가입 화면은 차단 응답을 폼 안에서 안내한다. 관리자 세션은 회원 세션과 따로 처리한다.
const INLINE_BLOCKED = new Set([
  '/api/v1/auth/login',
  '/api/v1/auth/signup',
  '/api/v1/auth/social/signup',
]);
const BLOCKED_NOTICE_PATH = '/login?notice=blocked';

/** 차단 안내로 이동한다. 새로 불러와 화면에 남은 개인 자료도 함께 비운다. 테스트에서 바꿔 끼운다. */
export const sessionNavigation = {
  toBlockedNotice: () => window.location.assign(BLOCKED_NOTICE_PATH),
};

let blockedHandling = false;

function handlesBlocked(api: string) {
  const path = api.split('?')[0];
  return !INLINE_BLOCKED.has(path) && !path.startsWith('/api/v1/admin');
}

/** 사용 중 차단: 서버 세션을 끊고, 개인 상태를 비운 뒤 시작 화면에서 안내한다. */
async function endBlockedSession() {
  if (blockedHandling) return;
  blockedHandling = true;
  try {
    // 차단된 세션은 모든 요청을 거절하므로 쿠키를 끊어 둔다. 실패해도 화면 정리는 계속한다.
    await fetch(
      `${API_BASE_URL}/api/v1/auth/logout`,
      createRequestOptions('POST', undefined),
    ).catch(() => undefined);
    useAuthStore.getState().clearSession();
    sessionNavigation.toBlockedNotice();
  } finally {
    blockedHandling = false;
  }
}

/** 목표 계약의 오류 응답 `{ error: { code, message, details } }`를 담는다. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  /** 같은 요청을 다시 보내면 나아질 수 있는지(계약의 error.retryable). 서버가 주지 않으면 null */
  readonly retryable: boolean | null;

  constructor(
    status: number,
    code: string | null,
    message: string,
    retryable: boolean | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

async function toApiError(response: Response) {
  let code: string | null = null;
  let message = response.statusText || `HTTP ${response.status}`;
  let retryable: boolean | null = null;
  try {
    const body = (await response.json()) as ErrorBody;
    if (typeof body.error?.code === 'string') code = body.error.code;
    if (typeof body.error?.message === 'string') message = body.error.message;
    if (typeof body.error?.retryable === 'boolean')
      retryable = body.error.retryable;
  } catch {
    // 본문이 JSON이 아니면 상태 문구만 쓴다.
  }
  return new ApiError(response.status, code, message, retryable);
}

function createRequestOptions(
  method: string,
  request: unknown,
  extraHeaders?: Record<string, string>,
  skipMemberCsrf = false,
): RequestInit {
  const headers = new Headers({
    ...extraHeaders,
    'Content-Type': 'application/json',
  });
  const csrfToken = useAuthStore.getState().session?.csrfToken;
  // 호출부가 직접 준 CSRF(예: 관리자 세션 토큰)는 회원 토큰으로 덮어쓰지 않는다.
  if (
    csrfToken &&
    !skipMemberCsrf &&
    !headers.has('X-CSRF-Token') &&
    !SAFE_METHODS.has(method.toUpperCase())
  ) {
    headers.set('X-CSRF-Token', csrfToken);
  }

  return {
    method,
    headers,
    credentials: 'include',
    ...(request !== undefined && request !== null
      ? { body: JSON.stringify(request) }
      : {}),
  };
}

export async function call<TResponse = unknown>(
  api: string,
  method: string,
  request?: unknown,
  option?: CallOptions,
): Promise<TResponse> {
  const skipAuth = option?.skipAuth ?? false;
  const revision = useAuthStore.getState().sessionRevision;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${api}`, {
      ...createRequestOptions(
        method,
        request,
        option?.headers,
        option?.skipMemberCsrf,
      ),
      ...(option?.keepalive ? { keepalive: true } : {}),
    });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '요청을 보내지 못했어요.', true);
  }

  if (!response.ok) {
    const error = await toApiError(response);
    // 차단은 CSRF가 남아 있을 때 서버 세션부터 끊어야 하므로 세션 만료 처리보다 먼저 한다.
    if (error.code === 'MEMBER_BLOCKED' && handlesBlocked(api)) {
      await endBlockedSession();
      throw error;
    }
    // 세션이 끝났으면 화면의 로그인 상태를 비운다. 이동은 보호 라우트가 맡는다.
    if (
      response.status === 401 &&
      !skipAuth &&
      revision === useAuthStore.getState().sessionRevision
    ) {
      useAuthStore.getState().clearSession();
    }
    throw error;
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }

  try {
    return (await response.json()) as TResponse;
  } catch {
    throw new ApiError(
      response.status,
      'INVALID_RESPONSE',
      '응답을 확인하지 못했어요.',
    );
  }
}
