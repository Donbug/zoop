import { useEffect, useRef, useState } from 'react';
import { getGraph } from '@/apis/graph/graph';
import type { GraphRequest, GraphResponse } from '@/types/map/graph';

export function useGraphData(
  request: GraphRequest,
  session: string | null,
  retry: number,
) {
  const [state, setState] = useState<{
    data: GraphResponse | null;
    error: string | null;
    loading: boolean;
    session: string | null;
  }>({ data: null, error: null, loading: true, session });
  const latest = useRef(0);
  const { mode, personalFilter, companyId } = request;
  useEffect(() => {
    const sequence = ++latest.current;
    // Async transition avoids synchronous effect updates and preserves the last good graph.
    void Promise.resolve().then(async () => {
      if (sequence !== latest.current) return;
      setState((old) => ({
        ...old,
        data: old.session === session ? old.data : null,
        session,
        loading: true,
        error: null,
      }));
      try {
        const data = await getGraph({ mode, personalFilter, companyId });
        if (sequence === latest.current)
          setState({ data, error: null, loading: false, session });
      } catch (error) {
        if (sequence === latest.current)
          setState((old) => ({
            ...old,
            loading: false,
            error:
              error instanceof Error
                ? error.message
                : '그래프를 불러오지 못했습니다.',
          }));
      }
    });
    return () => {
      latest.current = sequence + 1;
    };
  }, [mode, personalFilter, companyId, session, retry]);
  // Never flash a previous member's personal response after logout/session replacement.
  return state.session === session
    ? state
    : { ...state, data: null, error: null, loading: true };
}
