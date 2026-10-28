import { directEdges, issues } from '@/mocks/graph/fixture';
import type { Impact } from '@/types/company/detail';

export type ImpactMockScenario = 'success' | 'empty' | 'error';

export function createMockImpact(
  companyId: string,
  issueId: string,
  scenario: ImpactMockScenario = 'success',
): Impact {
  const issue = issues.find((item) => item.id === issueId);
  const relation = directEdges.find(
    (edge) => edge.source === issueId && edge.target === companyId,
  );
  if (!issue || !relation)
    throw new Error('선택한 기업과 사건의 연결을 찾을 수 없습니다.');

  return {
    companyId,
    issueId,
    pathStatus:
      scenario === 'empty' ? 'no_direct_relation' : 'direct_available',
    steps:
      scenario === 'empty'
        ? []
        : [
            {
              id: issueId,
              kind: 'issue',
              reason: relation.summary || '직접 관련',
              evidenceIds: relation.evidenceIds,
            },
            {
              id: companyId,
              kind: 'company',
              reason: '선택한 기업',
              evidenceIds: relation.evidenceIds,
            },
          ],
    metadata: {
      source: 'MOCK · ERD v6 기반 가상 데이터',
      asOf: '2026-10-06T03:41:00Z',
      graphVersion: 'mock-graph-v1',
      partial: false,
      failures: [],
    },
  };
}
