import { useEffect, useRef, useState, type RefObject } from 'react';
import { getGraph } from '@/apis/graph/graph';
import { BriefingGraphUnavailableError } from '@/apis/graph/briefing-context';
import type { GraphRequest, GraphResponse } from '@/types/map/graph';

export type GraphPrefetch = { key: string; data: GraphResponse };
export const graphRequestKey = (
  request: GraphRequest,
  session: string | null,
) =>
  JSON.stringify([
    session,
    request.mode,
    request.personalFilter,
    request.companyId,
    request.asOf,
    request.graphVersion,
    request.depth,
    request.round,
  ]);

export function useGraphData(
  request: GraphRequest,
  session: string | null,
  retry: number,
  prefetched?: RefObject<GraphPrefetch | null>,
) {
  const snapshotKey = JSON.stringify([
    request.companyId,
    request.asOf,
    request.graphVersion,
    request.depth,
    request.round,
  ]);
  const [state, setState] = useState<{
    data: GraphResponse | null;
    error: string | null;
    /** 회차 지도가 실패가 아니라 제공되지 않는 상태(D-BRF-04). 값은 API가 준 사유다. */
    unavailableReason: string | null;
    loading: boolean;
    session: string | null;
    snapshotKey: string;
  }>({
    data: null,
    error: null,
    unavailableReason: null,
    loading: true,
    session,
    snapshotKey,
  });
  const latest = useRef(0);
  const { mode, personalFilter, companyId, asOf, graphVersion, depth, round } =
    request;
  useEffect(() => {
    const sequence = ++latest.current;
    // Async transition avoids synchronous effect updates and preserves the last good graph.
    void Promise.resolve().then(async () => {
      if (sequence !== latest.current) return;
      setState((old) => ({
        ...old,
        data:
          old.session === session && old.snapshotKey === snapshotKey
            ? old.data
            : null,
        session,
        snapshotKey,
        loading: true,
        error: null,
        unavailableReason: null,
      }));
      try {
        const input = {
          mode,
          personalFilter,
          companyId,
          asOf,
          graphVersion,
          depth,
          round,
        };
        const cached = prefetched?.current;
        const data =
          cached?.key === graphRequestKey(input, session)
            ? cached.data
            : await getGraph(input);
        if (cached && prefetched?.current === cached) prefetched.current = null;
        if (sequence === latest.current)
          setState({
            data,
            error: null,
            unavailableReason: null,
            loading: false,
            session,
            snapshotKey,
          });
      } catch (error) {
        if (sequence === latest.current)
          setState((old) => ({
            ...old,
            data: round ? null : old.data,
            loading: false,
            unavailableReason:
              error instanceof BriefingGraphUnavailableError
                ? error.reason
                : null,
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
  }, [
    mode,
    personalFilter,
    companyId,
    asOf,
    graphVersion,
    depth,
    round,
    session,
    retry,
    snapshotKey,
    prefetched,
  ]);
  // Never flash a previous member's personal response after logout/session replacement.
  return state.session === session && state.snapshotKey === snapshotKey
    ? state
    : {
        ...state,
        data: null,
        error: null,
        unavailableReason: null,
        loading: true,
      };
}
