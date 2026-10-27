import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import type { Reload, ReloadOptions } from './useAsyncData';

type Page = { items: unknown[]; nextCursor: string | null };

type State<P> = {
  load: unknown;
  attempt: number;
  pages: P[];
  error: Error | null;
  loadingMore: boolean;
  moreError: Error | null;
  refreshError?: Error;
};

function toError(error: unknown) {
  return error instanceof Error ? error : new Error(String(error));
}

/**
 * 불투명 커서(nextCursor) 목록. 첫 쪽을 읽고, loadMore()로 다음 쪽을 이어 붙인다.
 * `load`가 바뀌면(조회 조건 변경) 처음부터 다시 읽고, 늦게 도착한 이전 조건의 응답은 버린다.
 * `load`는 렌더마다 새로 만들지 않는다(useCallback).
 */
export function useCursorPages<P extends Page>(
  load: (cursor?: string) => Promise<P>,
) {
  const [request, setRequest] = useState<{
    attempt: number;
    quiet: boolean;
    count: number;
    countFor?: typeof load;
    accept?: () => boolean;
  }>({ attempt: 0, quiet: false, count: 1 });
  const { attempt, quiet, accept } = request;
  const pageCount = request.countFor === load ? request.count : 1;
  const [state, setState] = useState<State<P> | null>(null);
  const busy = useRef(false);

  useEffect(() => {
    let active = true;
    busy.current = true;
    async function readPages() {
      const pages = [await load()];
      while (active && pages.length < pageCount && pages.at(-1)?.nextCursor) {
        pages.push(await load(pages.at(-1)!.nextCursor!));
      }
      return pages;
    }
    void readPages().then(
      (pages) => {
        if (active) busy.current = false;
        if (active)
          setState((previous) =>
            quiet && accept?.() === false && previous?.load === load
              ? { ...previous, attempt }
              : {
                  load,
                  attempt,
                  pages,
                  error: null,
                  loadingMore: false,
                  moreError: null,
                },
          );
      },
      (error: unknown) => {
        if (active) busy.current = false;
        if (active)
          setState((previous) =>
            quiet && previous?.load === load && previous.pages.length > 0
              ? {
                  ...previous,
                  attempt,
                  loadingMore: false,
                  refreshError: toError(error),
                }
              : {
                  load,
                  attempt,
                  pages: [],
                  error: toError(error),
                  loadingMore: false,
                  moreError: null,
                },
          );
      },
    );
    return () => {
      active = false;
    };
  }, [load, attempt, quiet, pageCount, accept]);

  const settled =
    state && state.load === load && (state.attempt === attempt || quiet)
      ? state
      : null;
  const pages = settled?.pages ?? [];
  const nextCursor = pages.at(-1)?.nextCursor ?? null;

  const loadMore = useCallback(() => {
    if (
      !settled ||
      !nextCursor ||
      settled.loadingMore ||
      settled.attempt !== attempt
    )
      return;
    // 조건이 바뀐 뒤 도착한 이전 조건의 다음 쪽은 버린다.
    const same = (previous: State<P> | null): previous is State<P> =>
      previous !== null &&
      previous.load === settled.load &&
      previous.attempt === settled.attempt;
    setState({ ...settled, loadingMore: true, moreError: null });
    load(nextCursor).then(
      (page) => {
        setState((previous) =>
          same(previous)
            ? {
                ...previous,
                pages: [...previous.pages, page],
                loadingMore: false,
              }
            : previous,
        );
      },
      (error: unknown) => {
        // 커서가 만료됐으면(INVALID_CURSOR) 같은 커서로 다시 보내지 않고 첫 쪽부터 다시 읽는다.
        if (error instanceof ApiError && error.code === 'INVALID_CURSOR') {
          setRequest((value) =>
            value.attempt === settled.attempt
              ? { attempt: value.attempt + 1, quiet: false, count: 1 }
              : value,
          );
          return;
        }
        setState((previous) =>
          same(previous)
            ? { ...previous, loadingMore: false, moreError: toError(error) }
            : previous,
        );
      },
    );
  }, [settled, nextCursor, load, attempt]);

  const reload: Reload = useCallback(
    (options?: ReloadOptions) => {
      if (
        options?.quiet &&
        (busy.current ||
          settled?.loadingMore ||
          (settled && settled.attempt !== attempt))
      )
        return;
      setRequest((value) => ({
        attempt: value.attempt + 1,
        quiet: options?.quiet === true,
        count: options?.quiet ? Math.max(1, settled?.pages.length ?? 1) : 1,
        countFor: load,
        accept: options?.accept,
      }));
    },
    [settled, attempt, load],
  );

  return {
    status: !settled ? 'loading' : settled.error ? 'error' : 'success',
    error: settled?.error ?? null,
    pages,
    items: pages.flatMap((page) => page.items) as P['items'],
    hasMore: nextCursor !== null,
    loadingMore: settled?.loadingMore ?? false,
    moreError: settled?.moreError ?? null,
    loadMore,
    reload,
    ...(settled?.refreshError ? { refreshError: settled.refreshError } : {}),
  } as const;
}
