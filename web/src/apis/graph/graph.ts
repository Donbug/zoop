import { call } from '@/apis/auth/ApiService';
import { getAccessToken } from '@/apis/auth/auth';
import type { GraphRequest, GraphResponse } from '@/types/map/graph';
import type { MockScenario } from '@/mocks/graph/response';

// Local mock is development-only; production always uses the real read endpoint.
export const usesGraphMock =
  import.meta.env.DEV && import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api';
export function graphUrl(request: GraphRequest) {
  const query = new URLSearchParams({ mode: request.mode });
  if (request.mode === 'personal')
    query.set('personalFilter', request.personalFilter);
  if (request.companyId) query.set('companyId', request.companyId);
  return `/api/v1/graph?${query}`;
}
export async function getGraph(request: GraphRequest): Promise<GraphResponse> {
  if (request.mode === 'personal' && !getAccessToken())
    throw new Error('개인화 지도는 로그인이 필요합니다.');
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
