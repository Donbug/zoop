// BFF 호출의 유일한 입구. 응답 타입은 BFF /openapi.json에서 생성한 schema.d.ts만 쓴다(`pnpm api:types`).
import type { components } from "./schema";

export type Schemas = components["schemas"];

/** BFF 오류 형식 {error:{code,message,details?}}와 네트워크 장애를 하나로 표현한다. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  signal?: AbortSignal;
}

export async function api<T>(path: string, { method = "GET", body, query, signal }: RequestOptions = {}): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const url = params.size > 0 ? `${path}?${params}` : path;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      signal,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "network_error", "서버에 연결하지 못했어요. 네트워크 상태를 확인해 주세요.");
  }

  if (response.status === 204) return undefined as T;

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null)?.error;
    if (error?.code) throw new ApiError(response.status, error.code, error.message ?? "요청을 처리하지 못했어요.", error.details ?? null);
    // Vite 프록시가 BFF에 닿지 못하면 JSON이 아닌 5xx를 돌려준다.
    throw new ApiError(response.status, "bff_unreachable", "BFF 서버에 연결하지 못했어요. 서버가 켜져 있는지 확인해 주세요.");
  }
  return payload as T;
}
