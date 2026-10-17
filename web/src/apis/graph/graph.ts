import { getBriefingGraphBasis } from '@/apis/briefing/briefing';
import { assertSnapshot } from './snapshot';
import { call } from '@/apis/auth/ApiService';
import { isMember } from '@/apis/auth/auth';
import type { GraphRequest, GraphResponse } from '@/types/map/graph';
import type { MockScenario } from '@/mocks/graph/response';

// Local mock is development-only; production always uses the real read endpoint.
export const usesGraphMock =
  import.meta.env.DEV && import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api';
export function graphUrl(request: GraphRequest) {
  const query = new URLSearchParams({ mode: request.mode });
  if (request.asOf) query.set('asOf', request.asOf);
  if (request.graphVersion) query.set('graphVersion', request.graphVersion);
  if (request.mode === 'personal')
    query.set('personalFilter', request.personalFilter);
  if (request.companyId) query.set('companyId', request.companyId);
  if (request.round) query.set('round', request.round);
  return `/api/v1/graph?${query}`;
}
export async function getGraph(request: GraphRequest): Promise<GraphResponse> {
  if (request.mode === 'personal' && !isMember())
    throw new Error('개인화 지도는 로그인이 필요합니다.');
  if (request.round) {
    const basis = await getBriefingGraphBasis(request.round);
    if (
      basis.roundId !== request.round ||
      basis.status !== 'available' ||
      !basis.graphVersion ||
      !basis.dataAsOf
    )
      throw new Error(
        basis.message ?? '이 회차의 그래프를 제공할 수 없습니다.',
      );
    const context = { graphVersion: basis.graphVersion, asOf: basis.dataAsOf };
    if (
      (request.graphVersion && request.graphVersion !== context.graphVersion) ||
      (request.asOf && Date.parse(request.asOf) !== Date.parse(context.asOf))
    )
      throw new Error('요청한 회차와 지도 기준이 일치하지 않습니다.');
    const graph = await call<GraphResponse>(
      graphUrl({ ...request, ...context, mode: 'all' }),
      'GET',
      undefined,
      { skipAuth: true },
    );
    assertSnapshot(graph.metadata, context);
    return graph;
  }
  if (request.companyId && request.asOf) {
    const query = new URLSearchParams({
      asOf: request.asOf,
      depth: String(request.depth ?? 1),
    });
    if (request.graphVersion) query.set('graphVersion', request.graphVersion);
    return call<GraphResponse>(
      `/api/v1/companies/${encodeURIComponent(request.companyId)}/graph?${query}`,
      'GET',
      undefined,
      { skipAuth: true },
    );
  }
  if (usesGraphMock) {
    const { createMockGraph } = await import('@/mocks/graph/response');
    const scenario = import.meta.env.VITE_GRAPH_MOCK_SCENARIO as
      MockScenario | undefined;
    await new Promise((resolve) => setTimeout(resolve, 220));
    if (scenario === 'error')
      throw new Error('Mock 조회 실패 · 다시 시도해 주세요.');
    return createMockGraph(request, scenario);
  }
  return call<GraphResponse>(graphUrl(request), 'GET', undefined, {
    skipAuth: request.mode === 'all',
  });
}
