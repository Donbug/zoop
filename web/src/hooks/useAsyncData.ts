import { useCallback, useEffect, useRef, useState } from 'react';

export type AsyncResult<T> =
  | { status: 'loading'; data: undefined; error: undefined }
  | { status: 'success'; data: T; error: undefined }
  | { status: 'error'; data: undefined; error: Error };

type Settled<T> = {
  load: () => Promise<T>;
  attempt: number;
  result: AsyncResult<T>;
  refreshError?: Error;
};

export type ReloadOptions = { quiet: boolean; accept?: () => boolean };
export type Reload = { (): void; (options: ReloadOptions): void };

const LOADING = { status: 'loading', data: undefined, error: undefined };

function toError(error: unknown) {
  return error instanceof Error ? error : new Error(String(error));
}

/**
 * 서버 상태 한 건을 조회한다(조회 캐시 도구는 미도입).
 * `load`가 바뀌거나 reload()를 부르면 다시 조회하고, 그 사이에는 loading이다. quiet 갱신은 같은 조회의 이전 성공 결과를 유지한다.
 * 늦게 도착한 이전 응답은 버린다. `load`는 렌더마다 새로 만들지 않는다(모듈 함수나 useCallback).
 */
export function useAsyncData<T>(load: () => Promise<T>) {
  const [request, setRequest] = useState<{
    attempt: number;
    quiet: boolean;
    accept?: () => boolean;
  }>({ attempt: 0, quiet: false });
  const { attempt, quiet, accept } = request;
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const busy = useRef(false);

  useEffect(() => {
    let active = true;
    busy.current = true;
    load().then(
      (data) => {
        if (active) busy.current = false;
        if (active)
          setSettled((previous) =>
            quiet && accept?.() === false && previous?.load === load
              ? { ...previous, attempt }
              : {
                  load,
                  attempt,
                  result: { status: 'success', data, error: undefined },
                },
          );
      },
      (error: unknown) => {
        if (active) busy.current = false;
        if (active)
          setSettled((previous) =>
            quiet &&
            previous?.load === load &&
            previous.result.status === 'success'
              ? { ...previous, attempt, refreshError: toError(error) }
              : {
                  load,
                  attempt,
                  result: {
                    status: 'error',
                    data: undefined,
                    error: toError(error),
                  },
                },
          );
      },
    );
    return () => {
      active = false;
    };
  }, [load, attempt, quiet, accept]);

  const reload: Reload = useCallback((options?: ReloadOptions) => {
    if (options?.quiet && busy.current) return;
    setRequest((value) => ({
      attempt: value.attempt + 1,
      quiet: options?.quiet === true,
      accept: options?.accept,
    }));
  }, []);

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
    settled && settled.load === load && (settled.attempt === attempt || quiet)
      ? settled.result
      : (LOADING as AsyncResult<T>);

  return {
    ...current,
    reload,
    setData,
    ...(settled?.load === load && settled.refreshError
      ? { refreshError: settled.refreshError }
      : {}),
  };
}

export type AsyncData<T> = ReturnType<typeof useAsyncData<T>>;
