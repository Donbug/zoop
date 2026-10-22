import { vi } from 'vitest';

// 테스트용 가짜 API 서버. 전역 fetch를 바꿔 끼워 `call()`이 보내는 요청을
// 등록한 처리기로 응답한다. 등록하지 않은 요청은 실패시켜 누락을 드러낸다.

export type FakeRequest = {
  method: string;
  path: string;
  query: URLSearchParams;
  params: Record<string, string>;
  body: unknown;
  headers: Headers;
};

type Handler = (request: FakeRequest) => Response | Promise<Response>;

type Route = {
  method: string;
  pattern: string;
  handler: Handler;
};

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function noContent() {
  return new Response(null, { status: 204 });
}

/** 목표 계약의 오류 응답 `{ error: { code, message, details } }` */
export function apiError(status: number, code: string, message = code) {
  return json({ error: { code, message, details: null } }, status);
}

/** 테스트가 원하는 때에 응답을 보내도록 미뤄 둔다(저장 중 상태 확인용). */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function matchPath(pattern: string, path: string) {
  const patternParts = pattern.split('/');
  const pathParts = path.split('/');
  if (patternParts.length !== pathParts.length) return null;
  const params: Record<string, string> = {};
  for (let index = 0; index < patternParts.length; index += 1) {
    const expected = patternParts[index];
    const actual = pathParts[index];
    if (expected.startsWith(':')) {
      params[expected.slice(1)] = decodeURIComponent(actual);
    } else if (expected !== actual) {
      return null;
    }
  }
  return params;
}

function toUrl(input: RequestInfo | URL) {
  if (typeof input === 'string') return new URL(input, 'http://localhost');
  if (input instanceof URL) return input;
  return new URL(input.url, 'http://localhost');
}

export function createFakeServer() {
  const routes: Route[] = [];
  const requests: FakeRequest[] = [];

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = toUrl(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      const body =
        typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;

      // 나중에 등록한 처리기가 앞선 처리기를 덮는다(테스트 중 응답 바꾸기).
      for (let index = routes.length - 1; index >= 0; index -= 1) {
        const route = routes[index];
        if (route.method !== method) continue;
        const params = matchPath(route.pattern, url.pathname);
        if (!params) continue;
        const request: FakeRequest = {
          method,
          path: url.pathname,
          query: url.searchParams,
          params,
          body,
          headers: new Headers(init?.headers),
        };
        requests.push(request);
        return route.handler(request);
      }

      throw new Error(`처리기가 없는 요청: ${method} ${url.pathname}`);
    },
  );

  vi.stubGlobal('fetch', fetchMock);

  return {
    on(method: string, pattern: string, handler: Handler) {
      routes.push({ method, pattern, handler });
    },
    requests,
    /** 경로 패턴(`:id` 허용)과 메서드로 지금까지 받은 요청을 고른다. */
    calls(method: string, pattern: string) {
      return requests.filter(
        (request) =>
          request.method === method && matchPath(pattern, request.path),
      );
    },
  };
}

export type FakeServer = ReturnType<typeof createFakeServer>;
