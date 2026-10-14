import { useCallback, useEffect, useState } from 'react';

export type AsyncResult<T> =
  | { status: 'loading'; data: undefined; error: undefined }
  | { status: 'success'; data: T; error: undefined }
  | { status: 'error'; data: undefined; error: Error };

type Settled<T> = {
  load: () => Promise<T>;
  attempt: number;
  result: AsyncResult<T>;
};

const LOADING = { status: 'loading', data: undefined, error: undefined };

function toError(error: unknown) {
  return error instanceof Error ? error : new Error(String(error));
}

/**
 * 서버 상태 한 건을 조회한다(조회 캐시 도구는 미도입).
 * `load`가 바뀌거나 reload()를 부르면 다시 조회하고, 그 사이에는 loading이다.
 * 늦게 도착한 이전 응답은 버린다. `load`는 렌더마다 새로 만들지 않는다(모듈 함수나 useCallback).
 */
export function useAsyncData<T>(load: () => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    let active = true;
    load().then(
      (data) => {
        if (active)
          setSettled({
            load,
            attempt,
            result: { status: 'success', data, error: undefined },
          });
      },
      (error: unknown) => {
        if (active)
          setSettled({
            load,
            attempt,
            result: { status: 'error', data: undefined, error: toError(error) },
          });
      },
    );
    return () => {
      active = false;
    };
  }, [load, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  /** 저장 응답처럼 서버가 돌려준 최신 값으로 바꾼다. */
  const setData = useCallback(
    (data: T) =>
      setSettled({
        load,
        attempt,
        result: { status: 'success', data, error: undefined },
      }),
    [load, attempt],
  );

  const current =
    settled && settled.load === load && settled.attempt === attempt
      ? settled.result
      : (LOADING as AsyncResult<T>);

  return { ...current, reload, setData };
}

export type AsyncData<T> = ReturnType<typeof useAsyncData<T>>;
