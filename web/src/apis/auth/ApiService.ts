import { API_BASE_URL } from './api-config';
import { useAuthStore } from '@/stores/useAuthStore';

// 목표 계약(docs/api/openapi.yaml)의 인증: HttpOnly 세션 쿠키(zoop_session)와
// 세션에 결합된 X-CSRF-Token. 브라우저는 토큰을 저장하지 않고 쿠키를 그대로 보낸다.

type CallOptions = {
  /** 공개 API. 401을 받아도 세션 만료로 처리하지 않는다. */
  skipAuth?: boolean;
  /** 요청별 추가 헤더(예: 목표 계약의 Idempotency-Key) */
  headers?: Record<string, string>;
};

type ErrorBody = {
  error?: {
    code?: unknown;
    message?: unknown;
  };
};

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/** 목표 계약의 오류 응답 `{ error: { code, message, details } }`를 담는다. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function toApiError(response: Response) {
  let code: string | null = null;
  let message = response.statusText || `HTTP ${response.status}`;
  try {
    const body = (await response.json()) as ErrorBody;
    if (typeof body.error?.code === 'string') code = body.error.code;
    if (typeof body.error?.message === 'string') message = body.error.message;
  } catch {
    // 본문이 JSON이 아니면 상태 문구만 쓴다.
  }
  return new ApiError(response.status, code, message);
}

function createRequestOptions(
  method: string,
  request: unknown,
  extraHeaders?: Record<string, string>,
): RequestInit {
  const headers = new Headers({
    ...extraHeaders,
    'Content-Type': 'application/json',
  });
  const csrfToken = useAuthStore.getState().session?.csrfToken;
  if (csrfToken && !SAFE_METHODS.has(method.toUpperCase())) {
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
  const response = await fetch(
    `${API_BASE_URL}${api}`,
    createRequestOptions(method, request, option?.headers),
  );

  if (!response.ok) {
    // 세션이 끝났으면 화면의 로그인 상태를 비운다. 이동은 보호 라우트가 맡는다.
    if (response.status === 401 && !skipAuth) {
      useAuthStore.getState().clearSession();
    }
    throw await toApiError(response);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }

  return (await response.json()) as TResponse;
}
