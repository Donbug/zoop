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
};

type ErrorBody = {
  error?: {
    code?: unknown;
    message?: unknown;
    retryable?: unknown;
  };
};

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

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
    response = await fetch(
      `${API_BASE_URL}${api}`,
      createRequestOptions(
        method,
        request,
        option?.headers,
        option?.skipMemberCsrf,
      ),
    );
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '요청을 보내지 못했어요.', true);
  }

  if (!response.ok) {
    // 세션이 끝났으면 화면의 로그인 상태를 비운다. 이동은 보호 라우트가 맡는다.
    if (
      response.status === 401 &&
      !skipAuth &&
      revision === useAuthStore.getState().sessionRevision
    ) {
      useAuthStore.getState().clearSession();
    }
    throw await toApiError(response);
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
