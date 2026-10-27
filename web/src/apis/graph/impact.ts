import type { EventContext } from '@/types/map/event';
import { snapshotUrl, assertSnapshot } from './snapshot';
import { call } from '@/apis/auth/ApiService';
import type { ImpactMockScenario } from '@/mocks/impact/fixture';
import { getRelation } from './relations';
import type { Impact } from '@/types/company/detail';

export const usesImpactMock =
  import.meta.env.DEV && import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api';

export function impactUrl(companyId: string, issueId: string) {
  return `/api/v1/companies/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/impact`;
}

export async function getCompanyIssueImpact(
  companyId: string,
  issueId: string,
  context: EventContext = {},
): Promise<Impact> {
  if (usesImpactMock && !context.round) {
    const { createMockImpact } = await import('@/mocks/impact/fixture');
    const scenario = import.meta.env.VITE_IMPACT_MOCK_SCENARIO as
      ImpactMockScenario | undefined;
    await new Promise((resolve) => setTimeout(resolve, 160));
    if (scenario === 'error')
      throw new Error('Mock 영향 경로 조회 실패 · 다시 시도해 주세요.');
    return createMockImpact(companyId, issueId, scenario);
  }

  const impact = await call<Impact>(
    snapshotUrl(impactUrl(companyId, issueId), context),
    'GET',
    undefined,
    {
      skipAuth: true,
    },
  );
  if (impact.companyId !== companyId || impact.issueId !== issueId)
    throw new Error('요청한 영향 경로와 응답이 일치하지 않습니다.');
  if (context.round || context.graphVersion || context.asOf)
    assertSnapshot(impact.metadata, context);
  return impact;
}

/** Tutorial follows one real approved edge already shown by the main map. */
export async function getTutorialImpact(
  companyId: string,
  issueId: string,
  edgeId: string,
  context: EventContext = {},
): Promise<Impact> {
  const relation = await getRelation(edgeId, context);
  const endpoints = new Set([relation.source.id, relation.target.id]);
  if (
    relation.derived ||
    !['INVOLVES', 'STRUCTURALLY_RELATED_TO'].includes(relation.relationType) ||
    !endpoints.has(companyId) ||
    !endpoints.has(issueId) ||
    relation.verification.status !== 'ALLOW' ||
    relation.metadata.partial
  ) {
    throw new Error('현재 지도의 승인된 기업·사건 연결을 확인하지 못했어요.');
  }
  const evidenceIds = [...new Set(relation.evidenceIds)];
  return {
    companyId,
    issueId,
    steps: [
      {
        id: companyId,
        kind: 'company',
        reason: relation.role ?? relation.summary,
        evidenceIds,
      },
      { id: issueId, kind: 'issue', reason: relation.summary, evidenceIds },
    ],
    metadata: relation.metadata,
  };
}
