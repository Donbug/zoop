import { useCallback, useRef } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { createIdempotencyKey } from '@/apis/portfolio/portfolio';

/**
 * 관리 작업의 Idempotency-Key (docs/api/openapi.yaml `idempotency`).
 * - 응답을 받지 못했거나(네트워크·5xx·429) 같은 내용을 다시 보내면 같은 키를 써서 한 번만 처리되게 한다.
 * - 내용이 바뀌면 새 키를 쓴다. 같은 키에 다른 본문은 409 IDEMPOTENCY_CONFLICT다.
 * - 서버가 확정적으로 거절한(4xx) 뒤에는 새 키로 다시 보낸다. 같은 키는 저장된 거절을 그대로 돌려줄 수 있다.
 */
export function useIdempotencyKey() {
  const last = useRef<{ payload: string; key: string } | null>(null);

  const keyFor = useCallback((payload: unknown) => {
    const text = JSON.stringify(payload);
    if (last.current?.payload !== text)
      last.current = { payload: text, key: createIdempotencyKey() };
    return last.current.key;
  }, []);

  const settle = useCallback((error: unknown) => {
    if (
      error instanceof ApiError &&
      error.status >= 400 &&
      error.status < 500 &&
      error.status !== 429
    )
      last.current = null;
  }, []);

  return { keyFor, settle };
}
