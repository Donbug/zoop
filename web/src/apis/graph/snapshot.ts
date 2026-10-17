import type { EventContext } from '@/types/map/event';

export function snapshotUrl(url: string, context: EventContext) {
  const query = new URLSearchParams();
  for (const key of ['round', 'graphVersion', 'asOf'] as const)
    if (context[key]) query.set(key, context[key]);
  return `${url}${query.size ? `${url.includes('?') ? '&' : '?'}${query}` : ''}`;
}

export function assertSnapshot(
  metadata: { graphVersion?: string | null; asOf?: string } | undefined,
  context: EventContext,
) {
  if (
    (context.graphVersion && metadata?.graphVersion !== context.graphVersion) ||
    (context.asOf &&
      Date.parse(metadata?.asOf ?? '') !== Date.parse(context.asOf))
  )
    throw new Error('회차의 데이터 버전·기준 시점과 응답이 일치하지 않습니다.');
}
