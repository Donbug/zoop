import { getBriefingGraphBasis } from '@/apis/briefing/briefing';
import { BriefingGraphUnavailableError } from './briefing-context';
import { assertSnapshot } from './snapshot';
import { call } from '@/apis/auth/ApiService';
import { readCompanyResource } from '@/apis/company/company';
import { isMember } from '@/apis/auth/auth';
import type { GraphRequest, GraphResponse } from '@/types/map/graph';
import type { MockScenario } from '@/mocks/graph/response';
import { getSettings } from '@/apis/settings/settings';
import { getPortfolio } from '@/apis/portfolio/portfolio';
import { withCatalogCompanies, withMemberCompanies } from './catalog-companies';

// Local mock is development-only; production always uses the real read endpoint.
export const usesGraphMock =
  import.meta.env.DEV && import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api';
export function graphUrl(request: GraphRequest) {
  const query = new URLSearchParams({ mode: request.mode });
  if (request.asOf) query.set('asOf', request.asOf);
  if (request.graphVersion) query.set('graphVersion', request.graphVersion);
  if (request.mode === 'personal')
    query.set('personalFilter', request.personalFilter);
  if (request.companyId) {
    query.set('companyId', request.companyId);
    // depth를 빼면 서버는 연결된 전체 묶음을 돌려준다. 화면에서 고른 1·2단계를 그대로 보낸다.
    if (request.depth) query.set('depth', String(request.depth));
  }
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
      throw new BriefingGraphUnavailableError(basis);
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
    if (!request.companyId) {
      const issueIds = new Set(
        graph.nodes
          .filter((node) => node.kind === 'issue')
          .map((node) => node.id),
      );
      const companies = new Set(
        graph.nodes
          .filter((node) => node.kind === 'company')
          .map((node) => node.id),
      );
      if (
        basis.keyIssueIds.some((id) => !issueIds.has(id)) ||
        basis.companyIds.some((id) => !companies.has(id))
      )
        throw new Error(
          '회차 핵심 이슈·관련 기업과 지도 응답이 일치하지 않습니다.',
        );
    }
    return graph;
  }
  if (request.companyId && request.asOf) {
    const query = new URLSearchParams({
      asOf: request.asOf,
      depth: String(request.depth ?? 1),
    });
    if (request.graphVersion) query.set('graphVersion', request.graphVersion);
    return readCompanyResource<GraphResponse>(
      `/api/v1/companies/${encodeURIComponent(request.companyId)}/graph?${query}`,
    );
  }
  if (usesGraphMock) {
    const { createMockGraph } = await import('@/mocks/graph/response');
    const scenario = import.meta.env.VITE_GRAPH_MOCK_SCENARIO as
      MockScenario | undefined;
    await new Promise((resolve) => setTimeout(resolve, 220));
    if (scenario === 'error')
      throw new Error('Mock 조회 실패 · 다시 시도해 주세요.');
    if (request.mode === 'personal') {
      // 개발 목데이터에서도 내 종목 지도는 실제 로그인 회원의 보유·관심 종목을 기준으로 그린다.
      const member = await loadMemberCompanies();
      if (member)
        return withMemberCompanies(
          createMockGraph(request, scenario, member),
          member,
        );
      return createMockGraph(request, scenario);
    }
    return marketMap(request, createMockGraph(request, scenario));
  }
  const graph = await call<GraphResponse>(graphUrl(request), 'GET', undefined, {
    skipAuth: request.mode === 'all',
  });
  return marketMap(request, graph);
}

/** 시장 전체 지도(기업 중심 보기 제외)에는 사건 없는 기업도 연결 없는 기업으로 보인다. */
function marketMap(request: GraphRequest, graph: GraphResponse) {
  return request.mode === 'all' && !request.companyId
    ? withCatalogCompanies(graph)
    : graph;
}

async function loadMemberCompanies() {
  if (!isMember()) return null;
  try {
    const [settings, portfolio] = await Promise.all([
      getSettings(),
      getPortfolio(),
    ]);
    return {
      holdings: portfolio.holdings.map((holding) => holding.companyId),
      watchlist: settings.watchlistIds,
    };
  } catch {
    return null;
  }
}
