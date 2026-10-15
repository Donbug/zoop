import { useEffect, useState } from 'react';
import { eventUrl, getEvent } from '@/apis/graph/events';
import type { EventContext, EventDetail } from '@/types/map/event';

export function useEventData(id: string, context: EventContext, retry: number) {
  const { round, graphVersion, asOf } = context;
  const key = `${eventUrl(id, context)}:${retry}`;
  const [state, setState] = useState<{
    key: string;
    data: EventDetail | null;
    error: string | null;
  }>({ key: '', data: null, error: null });
  useEffect(() => {
    let active = true;
    void getEvent(id, { round, graphVersion, asOf }).then(
      (data) => {
        if (active) setState({ key, data, error: null });
      },
      (error: unknown) => {
        if (active)
          setState({
            key,
            data: null,
            error:
              error instanceof Error
                ? error.message
                : '사건을 불러오지 못했습니다.',
          });
      },
    );
    return () => {
      active = false;
    };
  }, [id, round, graphVersion, asOf, key]);
  // A changed selection/context hides old content immediately, before effects run.
  return state.key === key
    ? { ...state, loading: false }
    : { data: null, error: null, loading: true };
}
