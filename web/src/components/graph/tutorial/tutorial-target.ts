import type { GraphResponse } from '@/types/map/graph';

export const SAMSUNG_ID = 'KRX:005930';

/** 실제 응답에 존재하는 기업과 직접/구조적 사건만 안내 대상으로 삼는다. */
export function tutorialTarget(data: GraphResponse | null, fallback: boolean) {
  if (!data) return null;
  const companies = data.nodes.filter((node) => node.kind === 'company');
  const candidates = fallback
    ? companies.filter((node) => node.id === SAMSUNG_ID)
    : [...companies.filter((node) => node.holding || node.watch), ...companies];
  for (const company of candidates) {
    const edges = data.edges
      .filter(
        (edge) =>
          !edge.derived &&
          (edge.relationType === 'INVOLVES' ||
            edge.relationType === 'STRUCTURALLY_RELATED_TO') &&
          (edge.source === company.id || edge.target === company.id),
      )
      .sort(
        (a, b) =>
          Number(b.evidenceIds.length > 0) - Number(a.evidenceIds.length > 0),
      );
    for (const edge of edges) {
      const issue = data.nodes.find(
        (node) =>
          node.kind === 'issue' &&
          node.id === (edge.source === company.id ? edge.target : edge.source),
      );
      if (issue) return { company, issue, edge };
    }
  }
  return null;
}
