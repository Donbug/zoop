import { useEffect, useState } from 'react';
import { getRelation } from '@/apis/graph/relations';
import { ApiError } from '@/apis/auth/ApiService';
import type { EventContext } from '@/types/map/event';
import type { RelationDetail } from '@/types/map/relation';

export function useRelationData(
  id: string,
  context: EventContext,
  retry: number,
) {
  const { round, graphVersion, asOf } = context;
  const key = JSON.stringify([id, round, graphVersion, asOf, retry]);
  const [state, setState] = useState<{
    key: string;
    data: RelationDetail | null;
    error: string | null;
    retryable: boolean;
  }>({ key: '', data: null, error: null, retryable: false });
  useEffect(() => {
    let active = true;
    void getRelation(id, { round, graphVersion, asOf }).then(
      (data) => {
        if (active) setState({ key, data, error: null, retryable: false });
      },
      (error: unknown) => {
        if (active)
          setState({
            key,
            data: null,
            error:
              error instanceof Error
                ? error.message
                : '연결선을 불러오지 못했습니다.',
            retryable: !(error instanceof ApiError) || error.status >= 500,
          });
      },
    );
    return () => {
      active = false;
    };
  }, [id, round, graphVersion, asOf, key]);
  return state.key === key
    ? { ...state, loading: false }
    : { data: null, error: null, retryable: false, loading: true };
}
