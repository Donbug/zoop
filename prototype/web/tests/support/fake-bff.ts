// BFF 대역. 앱이 부르는 `fetch`를 가로채 시험이 응답의 내용·지연·실패·도착 순서를 정한다.
//
// 브라우저와 같은 규칙을 지킨다:
//  - 앱이 요청을 취소(AbortSignal)하면 fetch는 AbortError로 거절되고, 그 뒤에 응답을 보내도 앱에는 닿지 않는다.
//  - 연결 실패는 TypeError로 거절된다(client.ts가 network_error로 바꾼다).
// 정의하지 않은 경로는 조용히 넘어가지 않고 시험을 실패시킨다(tests/support/app.tsx의 afterEach).
import { vi } from "vitest";
import { sleep } from "./time";

export type Method = "GET" | "POST" | "PUT" | "DELETE";

export type Reply = { kind: "response"; status: number; body?: unknown } | { kind: "network-down" };

export const json = (body: unknown, status = 200): Reply => ({ kind: "response", status, body });
export const noContent = (): Reply => ({ kind: "response", status: 204 });
/** BFF의 오류 형식 {error:{code,message}} */
export const apiError = (status: number, code: string, message = code): Reply => ({ kind: "response", status, body: { error: { code, message } } });
/** 연결이 끊겨 응답이 오지 않음. 서버가 요청을 처리했는지는 클라이언트가 알 수 없다. */
export const networkDown = (): Reply => ({ kind: "network-down" });

export interface RecordedRequest {
  readonly seq: number;
  readonly method: Method;
  /** 인코딩된 경로(쿼리 제외) */
  readonly path: string;
  readonly query: URLSearchParams;
  readonly body: unknown;
  /** 앱이 이 요청을 취소했는지 */
  aborted: boolean;
}

export type Params = Record<string, string>;
export type Handler = (request: RecordedRequest, params: Params) => Reply | Promise<Reply>;
export type Where = (request: RecordedRequest) => boolean;

interface Pattern {
  method: Method;
  regex: RegExp;
  keys: string[];
  where?: Where;
}

/** "/api/companies/:id/quote" 같은 경로 틀. `:id`는 한 구간이며 디코딩해서 params로 준다. */
function compile(method: Method, path: string, where?: Where): Pattern {
  const keys: string[] = [];
  const source = path
    .split("/")
    .map((segment) => {
      if (!segment.startsWith(":")) return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      keys.push(segment.slice(1));
      return "([^/]+)";
    })
    .join("/");
  return { method, regex: new RegExp(`^${source}$`), keys, where };
}

function match(pattern: Pattern, request: RecordedRequest): Params | null {
  if (pattern.method !== request.method) return null;
  const found = pattern.regex.exec(request.path);
  if (!found) return null;
  if (pattern.where && !pattern.where(request)) return null;
  return Object.fromEntries(pattern.keys.map((key, i) => [key, decodeURIComponent(found[i + 1]!)]));
}

interface Parked {
  settle: (reply: Reply) => void;
  /** 응답 단계에서 붙잡았을 때 서버가 이미 만든 응답 */
  computed?: Reply;
}

/**
 * 응답을 시험이 풀어 줄 때까지 붙잡아 두는 가로채기. 처음 `times`건(기본 1건)만 붙잡고, 풀고 나면 이후 요청은 원래 경로로 간다.
 *  - "request": 요청이 서버에 닿기 전에 붙잡힌다(서버는 아직 모른다).
 *  - "response": 서버는 요청을 처리했고(상태가 바뀌었고) 응답만 늦게 온다.
 */
export class Hold {
  readonly phase: "request" | "response";
  readonly #parked: Parked[] = [];
  #armed = true;
  #waiters: (() => void)[] = [];
  readonly #times: number;

  constructor(phase: "request" | "response", times: number) {
    this.phase = phase;
    this.#times = times;
  }

  /** @internal */
  park(parked: Parked) {
    this.#parked.push(parked);
    for (const wake of this.#waiters.splice(0)) wake();
  }

  /** 아직 붙잡을 요청이 남았는지: 풀기 전이고, 정한 횟수만큼 붙잡지 않았다. */
  get armed() {
    return this.#armed && this.#parked.length < this.#times;
  }

  /** 요청이 하나라도 붙잡힐 때까지 기다린다. */
  async arrived() {
    if (this.#parked.length > 0) return;
    const { promise, resolve } = Promise.withResolvers<void>();
    this.#waiters.push(resolve);
    await promise;
  }

  /** 붙잡은 요청에 응답한다. 응답 단계 가로채기는 인자를 생략하면 서버가 만든 응답을 그대로 보낸다. 앱이 이미 취소한 요청이면 앱에 닿지 않는다. */
  respond(reply?: Reply) {
    this.#armed = false;
    for (const { settle, computed } of this.#parked) {
      const final = reply ?? computed;
      if (!final) throw new Error("요청 단계 가로채기는 응답을 직접 줘야 한다");
      settle(final);
    }
  }
}

export class FakeBff {
  readonly requests: RecordedRequest[] = [];
  readonly unhandled: string[] = [];
  readonly #routes: { pattern: Pattern; handler: Handler }[] = [];
  readonly #holds: { pattern: Pattern; hold: Hold }[] = [];
  #seq = 0;
  #inFlight = 0;

  /** 경로 응답을 정한다. 같은 경로를 나중에 다시 정하면 나중 것이 우선한다. 반환한 함수로 되돌린다. */
  on(method: Method, path: string, handler: Handler | Reply, where?: Where) {
    const entry = { pattern: compile(method, path, where), handler: typeof handler === "function" ? handler : () => handler };
    this.#routes.unshift(entry);
    return () => {
      const at = this.#routes.indexOf(entry);
      if (at >= 0) this.#routes.splice(at, 1);
    };
  }

  /** 이 경로의 요청이 서버에 닿기 전에 붙잡는다. `where`로 쿼리(기간 등)까지 좁힌다. */
  hold(method: Method, path: string, where?: Where, times = 1) {
    return this.#addHold(new Hold("request", times), method, path, where);
  }

  /** 서버는 요청을 처리하지만 응답이 늦게 도착하게 한다(처리 결과를 알 수 없는 시간이 생긴다). */
  holdResponse(method: Method, path: string, where?: Where, times = 1) {
    return this.#addHold(new Hold("response", times), method, path, where);
  }

  #addHold(hold: Hold, method: Method, path: string, where?: Where) {
    this.#holds.push({ pattern: compile(method, path, where), hold });
    return hold;
  }

  #holdFor(phase: Hold["phase"], request: RecordedRequest) {
    return this.#holds.find(({ pattern, hold }) => hold.phase === phase && hold.armed && match(pattern, request))?.hold;
  }

  /** 지금까지 받은 요청 중 조건에 맞는 것. 경로를 생략하면 그 메서드 전체. */
  calls(method: Method, path?: string, where?: Where) {
    if (path === undefined) return this.requests.filter((r) => r.method === method && (!where || where(r)));
    const pattern = compile(method, path, where);
    return this.requests.filter((r) => match(pattern, r) !== null);
  }

  /** 데이터를 바꾸는 요청(GET 제외) */
  get writes() {
    return this.requests.filter((r) => r.method !== "GET");
  }

  /** 붙잡히지 않은 요청이 모두 응답될 때까지 기다린다. */
  async idle() {
    while (this.#inFlight > 0) await sleep(5);
  }

  /** 앱이 호출하는 `fetch` 자리에 꽂는다. */
  readonly fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const request: RecordedRequest = {
      seq: (this.#seq += 1),
      method: (init?.method ?? "GET").toUpperCase() as Method,
      path: url.pathname,
      query: url.searchParams,
      body: typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined,
      aborted: false,
    };
    this.requests.push(request);
    const signal = init?.signal ?? undefined;

    const { promise, resolve, reject } = Promise.withResolvers<Response>();
    const abort = () => {
      request.aborted = true;
      reject(signal?.reason instanceof DOMException ? signal.reason : new DOMException("The operation was aborted.", "AbortError"));
    };
    if (signal?.aborted) {
      abort();
      return promise;
    }
    signal?.addEventListener("abort", abort, { once: true });

    const deliver = (reply: Reply) => {
      if (request.aborted) return;
      signal?.removeEventListener("abort", abort);
      if (reply.kind === "network-down") reject(new TypeError("Failed to fetch"));
      else if (reply.status === 204) resolve(new Response(null, { status: 204 }));
      else resolve(new Response(JSON.stringify(reply.body ?? null), { status: reply.status, headers: { "Content-Type": "application/json" } }));
    };

    const before = this.#holdFor("request", request);
    if (before) {
      before.park({ settle: deliver });
      return promise;
    }

    this.#inFlight += 1;
    void this.#answer(request).then(
      (reply) => {
        this.#inFlight -= 1;
        const after = this.#holdFor("response", request);
        if (after) after.park({ settle: deliver, computed: reply });
        else deliver(reply);
      },
      (error: unknown) => {
        this.#inFlight -= 1;
        reject(error);
      },
    );
    return promise;
  };

  async #answer(request: RecordedRequest): Promise<Reply> {
    await sleep(0);
    for (const { pattern, handler } of this.#routes) {
      const params = match(pattern, request);
      if (params) return handler(request, params);
    }
    const label = `${request.method} ${request.path}${request.query.size > 0 ? `?${request.query}` : ""}`;
    this.unhandled.push(label);
    throw new Error(`fake BFF에 정의되지 않은 요청: ${label}`);
  }

  install() {
    vi.stubGlobal("fetch", this.fetch);
  }
}
