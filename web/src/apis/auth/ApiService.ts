import { API_BASE_URL } from './api-config';
import { clearAuthentication, getAccessToken, setAccessToken } from './auth';

type CallOptions = {
  skipAuth?: boolean;
  headers?: Record<string, string>;
};

type RefreshResponse = {
  data?: {
    accessToken?: {
      token?: unknown;
    };
  };
};

const REFRESH_API = '/api/v1/auth/refresh';

let refreshPromise: Promise<string> | null = null;

function moveToLogin() {
  if (window.location.pathname !== '/login') {
    window.location.replace('/login');
  }
}

async function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const response = await fetch(`${API_BASE_URL}${REFRESH_API}`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error(response.statusText || `HTTP ${response.status}`);
      }

      const body = (await response.json()) as RefreshResponse;
      const token = body.data?.accessToken?.token;

      if (typeof token !== 'string' || token.length === 0) {
        throw new Error('Access token is missing from refresh response');
      }

      setAccessToken(token);
      return token;
    })().finally(() => {
      refreshPromise = null;
    });
  }

  return refreshPromise;
}

function createRequestOptions(
  method: string,
  request: unknown,
  accessToken: string | null,
  skipAuth: boolean,
  extraHeaders?: Record<string, string>,
): RequestInit {
  const headers = new Headers({
    'Content-Type': 'application/json',
    ...extraHeaders,
  });

  if (accessToken && !skipAuth) {
    headers.set('Authorization', `Bearer ${accessToken}`);
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
  const url = `${API_BASE_URL}${api}`;
  const skipAuth = option?.skipAuth ?? false;
  const requestedWithToken = getAccessToken();

  let response = await fetch(
    url,
    createRequestOptions(
      method,
      request,
      requestedWithToken,
      skipAuth,
      option?.headers,
    ),
  );

  if (response.status === 401 && !skipAuth) {
    try {
      const latestToken = getAccessToken();
      const nextToken =
        latestToken && latestToken !== requestedWithToken
          ? latestToken
          : await refreshAccessToken();

      response = await fetch(
        url,
        createRequestOptions(
          method,
          request,
          nextToken,
          false,
          option?.headers,
        ),
      );
    } catch (error) {
      clearAuthentication();
      moveToLogin();
      throw error;
    }
  }

  if (!response.ok) {
    if (response.status === 401 && !skipAuth) {
      clearAuthentication();
      moveToLogin();
    }

    throw new Error(response.statusText || `HTTP ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }

  return (await response.json()) as TResponse;
}
