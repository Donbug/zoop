import { searchCompanies } from '@/apis/companies/companies';
import type { CompanySummary } from '@/types/company';
import type { GraphNode, GraphResponse } from '@/types/map/graph';

// D-GRP-01/01b: 그래프 스냅샷에는 사건이 있는 기업만 들어 있다. 기업 목록(카탈로그)의
// 나머지 기업은 연결 없는 기업으로 함께 보인다. 관계·사건은 만들지 않는다.

const MAX_PAGES = 10;

async function listCatalog(): Promise<CompanySummary[]> {
  const items: CompanySummary[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < MAX_PAGES; page++) {
    const response = await searchCompanies('', cursor);
    items.push(...response.items);
    if (!response.nextCursor) break;
    cursor = response.nextCursor;
  }
  return items;
}

function companyNode(
  company: CompanySummary,
  flags: Pick<GraphNode, 'isFocus' | 'holding' | 'watch'>,
): GraphNode {
  return {
    id: company.id,
    kind: 'company',
    label: company.name,
    ...flags,
    brandColor: company.brandColor,
    logoUrl: company.logoUrl,
    eventTime: null,
    timePrecision: null,
    action: null,
    target: null,
    evidenceCount: null,
    geography: null,
  };
}

/** 시장 전체 지도: 기업 목록에 있지만 지도에 없는 기업을 연결 없는 기업으로 더한다. */
export async function withCatalogCompanies(
  graph: GraphResponse,
): Promise<GraphResponse> {
  try {
    const shown = new Set(graph.nodes.map((node) => node.id));
    const missing = (await listCatalog()).filter(
      (company) => !shown.has(company.id),
    );
    if (!missing.length) return graph;
    return {
      ...graph,
      nodes: [
        ...graph.nodes,
        ...missing.map((company) =>
          companyNode(company, {
            isFocus: false,
            holding: false,
            watch: false,
          }),
        ),
      ],
    };
  } catch {
    // 기업 목록을 못 받아도 지도는 그대로 보인다.
    return graph;
  }
}

/** 개발 목데이터의 내 종목 지도: 목데이터에 없는 회원 기업을 보유·관심 표시와 함께 더한다. */
export async function withMemberCompanies(
  graph: GraphResponse,
  member: { holdings: string[]; watchlist: string[] },
): Promise<GraphResponse> {
  const shown = new Set(graph.nodes.map((node) => node.id));
  const wanted = [...new Set([...member.holdings, ...member.watchlist])].filter(
    (id) => !shown.has(id),
  );
  if (!wanted.length) return graph;
  try {
    const catalog = await listCatalog();
    const added = catalog
      .filter((company) => wanted.includes(company.id))
      .map((company) =>
        companyNode(company, {
          isFocus: true,
          holding: member.holdings.includes(company.id),
          watch: member.watchlist.includes(company.id),
        }),
      );
    return { ...graph, nodes: [...graph.nodes, ...added] };
  } catch {
    return graph;
  }
}
