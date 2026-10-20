import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';

type Page = { items: unknown[]; nextCursor: string | null };

type State<P> = {
  load: unknown;
  attempt: number;
  pages: P[];
  error: Error | null;
  loadingMore: boolean;
  moreError: Error | null;
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
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<State<P> | null>(null);

  useEffect(() => {
    let active = true;
    load().then(
      (page) => {
        if (active)
          setState({
            load,
            attempt,
            pages: [page],
            error: null,
            loadingMore: false,
            moreError: null,
          });
      },
      (error: unknown) => {
        if (active)
          setState({
            load,
            attempt,
            pages: [],
            error: toError(error),
            loadingMore: false,
            moreError: null,
          });
      },
    );
    return () => {
      active = false;
    };
  }, [load, attempt]);

  const settled =
    state && state.load === load && state.attempt === attempt ? state : null;
  const pages = settled?.pages ?? [];
  const nextCursor = pages.at(-1)?.nextCursor ?? null;

  const loadMore = useCallback(() => {
    if (!settled || !nextCursor || settled.loadingMore) return;
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
          setAttempt((value) =>
            value === settled.attempt ? value + 1 : value,
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
  }, [settled, nextCursor, load]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

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
  } as const;
}
