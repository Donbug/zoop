import type { GraphEdge, GraphRequest, GraphResponse } from '@/types/map/graph';
import { companies, directEdges, follows, issues, mockMember } from './fixture';

export type MockScenario = 'success' | 'empty' | 'no-relations' | 'error';
export function createMockGraph(
  request: GraphRequest,
  scenario: MockScenario = 'success',
  /** 내 종목 기준 회원. 개발 화면은 실제 로그인 회원의 보유·관심 종목을 넘긴다. */
  member: { holdings: string[]; watchlist: string[] } = mockMember,
): GraphResponse {
  const personal = request.mode === 'personal';
  const seeds = personal
    ? [
        ...new Set([
          ...(request.personalFilter !== 'watchlist' ? member.holdings : []),
          ...(request.personalFilter !== 'holdings' ? member.watchlist : []),
        ]),
      ]
    : [];
  const relatedIssues = new Set(
    directEdges.filter((e) => seeds.includes(e.target)).map((e) => e.source),
  );
  const edges = personal
    ? directEdges.filter((e) => relatedIssues.has(e.source))
    : directEdges;
  const companyIds = new Set([...seeds, ...edges.map((e) => e.target)]);
  let nodes = [
    ...companies.filter((n) => !personal || companyIds.has(n.id)),
    ...issues.filter((n) => !personal || relatedIssues.has(n.id)),
  ].map((n) => ({
    ...n,
    isFocus: personal ? seeds.includes(n.id) : n.id === 'NASDAQ:NVDA',
    holding: personal && member.holdings.includes(n.id),
    watch: personal && member.watchlist.includes(n.id),
  }));
  let visibleEdges: GraphEdge[] = [
    ...edges,
    ...follows.filter(
      (e) =>
        nodes.some((n) => n.id === e.source) &&
        nodes.some((n) => n.id === e.target),
    ),
  ];
  // SHARES_ISSUE is derived from approved common Issue IDs, never a saved SQL relation.
  const pairs = new Map<string, GraphEdge>();
  for (const issue of nodes.filter((n) => n.kind === 'issue')) {
    const participants = edges
      .filter((e) => e.source === issue.id)
      .map((e) => e.target)
      .sort();
    participants.forEach((source, i) =>
      participants.slice(i + 1).forEach((target) => {
        const id = `shared:${source}:${target}`;
        const existing = pairs.get(id);
        if (existing) existing.via.push(issue.id);
        else
          pairs.set(id, {
            id,
            source,
            target,
            relationType: 'SHARES_ISSUE',
            role: null,
            summary: '사건 공유',
            assertionStatus: null,
            derived: true,
            via: [issue.id],
            evidenceIds: [],
          });
      }),
    );
  }
  visibleEdges.push(...pairs.values());
  if (scenario === 'empty') {
    nodes = [];
    visibleEdges = [];
  }
  if (scenario === 'no-relations') {
    nodes = nodes.filter((n) =>
      personal ? seeds.includes(n.id) : n.kind === 'company',
    );
    visibleEdges = [];
  }
  return {
    nodes,
    edges: visibleEdges,
    metadata: {
      source: 'MOCK · ERD v6 기반 가상 데이터',
      asOf: '2026-10-06T03:41:00Z',
      graphVersion: 'mock-graph-v1',
      mode: request.mode,
      personalFilter: personal ? request.personalFilter : null,
      focusCompanyIds: nodes.filter((n) => n.isFocus).map((n) => n.id),
      depth: null,
      limit: 1000,
      requestId: 'mock-graph-request',
      truncated: false,
      partial: false,
      failures: [],
      emptyReason:
        scenario === 'empty'
          ? personal
            ? 'NO_BASE_COMPANIES'
            : 'NO_PUBLIC_DATA'
          : scenario === 'no-relations'
            ? 'NO_RELATIONS'
            : null,
    },
  };
}
