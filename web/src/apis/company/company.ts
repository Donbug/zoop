import type { Meta } from '@/types/company/detail';
import type { GraphResponse } from '@/types/map/graph';
import { ApiError, call } from '@/apis/auth/ApiService';
export function companyUrl(
  id: string,
  suffix = '',
  query: Record<string, string | number | null | undefined> = {},
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query))
    if (value !== null && value !== undefined && value !== '')
      params.set(key, String(value));
  return `/api/v1/companies/${encodeURIComponent(id)}${suffix}${params.size ? `?${params}` : ''}`;
}
export async function readCompanyResource<T>(
  url: string,
  paged = false,
): Promise<T> {
  const first = await call<T>(url, 'GET', undefined, {
    skipAuth: !url.startsWith('/api/v1/portfolio'),
  });
  const requested = new URL(url, 'http://localhost');
  const payload = first as { metadata?: { graphVersion?: string | null } };
  const expectedVersion = requested.searchParams.get('graphVersion');
  if (expectedVersion && payload.metadata?.graphVersion !== expectedVersion)
    throw new ApiError(
      409,
      'VERSION_UNAVAILABLE',
      '요청한 공개 버전과 다른 자료를 받았어요.',
    );
  const graphCompanyId = /^\/api\/v1\/companies\/([^/]+)\/graph$/.exec(
    requested.pathname,
  )?.[1];
  if (graphCompanyId) {
    const graph = first as GraphResponse;
    const expectedDepth = Number(requested.searchParams.get('depth') ?? 1);
    const expectedTime = Date.parse(requested.searchParams.get('asOf') ?? '');
    const actualTime = Date.parse(graph.metadata?.asOf ?? '');
    const focus = graph.metadata?.focusCompanyIds ?? [];
    if (
      !Number.isFinite(expectedTime) ||
      actualTime !== expectedTime ||
      graph.metadata?.depth !== expectedDepth ||
      ((graph.nodes.length > 0 || focus.length > 0) &&
        !focus.includes(decodeURIComponent(graphCompanyId)))
    )
      throw new ApiError(
        502,
        'INVALID_RESPONSE',
        '요청한 기업·시점·관계 단계와 다른 그래프를 받았어요.',
      );
  }
  if (!paged) return first;
  type Page = {
    items: { id: string }[];
    unknownTimeItems?: { id: string }[];
    nextCursor: string | null;
    metadata?: Meta;
  };
  const result = first as Page;
  const seen = new Set<string>();
  while (result.nextCursor) {
    const cursor = result.nextCursor;
    if (seen.has(cursor))
      throw new ApiError(200, 'INVALID_CURSOR', '페이지를 확인하지 못했어요.');
    seen.add(cursor);
    const path = new URL(url, 'http://localhost');
    path.searchParams.set('cursor', cursor);
    const next = await call<Page>(
      `${path.pathname}${path.search}`,
      'GET',
      undefined,
      { skipAuth: true },
    );
    if (
      next.metadata?.graphVersion !== result.metadata?.graphVersion ||
      next.metadata?.asOf !== result.metadata?.asOf
    )
      throw new ApiError(
        409,
        'REVISION_CONFLICT',
        '조회 중 공개 자료 기준이 바뀌었어요.',
      );
    if (result.metadata && next.metadata) {
      result.metadata.partial = Boolean(
        result.metadata.partial || next.metadata.partial,
      );
      result.metadata.failures = [
        ...(result.metadata.failures ?? []),
        ...(next.metadata.failures ?? []),
      ];
    }
    result.items.push(...next.items);
    if (next.unknownTimeItems)
      result.unknownTimeItems?.push(...next.unknownTimeItems);
    result.nextCursor = next.nextCursor;
  }
  if (new Set(result.items.map((i) => i.id)).size !== result.items.length)
    throw new ApiError(
      200,
      'INVALID_RESPONSE',
      '중복 자료를 확인하지 못했어요.',
    );
  return first;
}
