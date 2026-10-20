import { assertSnapshot } from './snapshot';
import { call } from '@/apis/auth/ApiService';
import type { EventContext, EventDetail } from '@/types/map/event';
import type { EventMockScenario } from '@/mocks/events/fixture';

export function eventUrl(id: string, context: EventContext = {}) {
  const query = new URLSearchParams();
  for (const key of ['round', 'graphVersion', 'asOf'] as const) {
    if (context[key]) query.set(key, context[key]);
  }
  return `/api/v1/events/${encodeURIComponent(id)}${query.size ? `?${query}` : ''}`;
}

export async function getEvent(
  id: string,
  context: EventContext = {},
): Promise<EventDetail> {
  // Same explicit opt-out as the map. Production never imports synthetic data.
  if (
    !context.round &&
    import.meta.env.DEV &&
    import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api'
  ) {
    const { createMockEvent } = await import('@/mocks/events/fixture');
    await new Promise((resolve) => setTimeout(resolve, 300));
    return createMockEvent(
      id,
      import.meta.env.VITE_EVENT_MOCK_SCENARIO as EventMockScenario | undefined,
      context,
    );
  }
  const event = await call<EventDetail>(
    eventUrl(id, context),
    'GET',
    undefined,
    { skipAuth: true },
  );
  if (event.id !== id)
    throw new Error('요청한 사건과 응답이 일치하지 않습니다.');
  if (
    context.graphVersion &&
    event.metadata.graphVersion !== context.graphVersion
  )
    throw new Error('지도의 데이터 버전과 사건 응답이 일치하지 않습니다.');
  if (context.round) assertSnapshot(event.metadata, context);
  return event;
}
