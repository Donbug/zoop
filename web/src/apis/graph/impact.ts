import { call } from '@/apis/auth/ApiService';
import type { ImpactMockScenario } from '@/mocks/impact/fixture';
import type { Impact } from '@/types/company/detail';

export const usesImpactMock =
  import.meta.env.DEV && import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api';

export function impactUrl(companyId: string, issueId: string) {
  return `/api/v1/companies/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/impact`;
}

export async function getCompanyIssueImpact(
  companyId: string,
  issueId: string,
): Promise<Impact> {
  if (usesImpactMock) {
    const { createMockImpact } = await import('@/mocks/impact/fixture');
    const scenario = import.meta.env.VITE_IMPACT_MOCK_SCENARIO as
      ImpactMockScenario | undefined;
    await new Promise((resolve) => setTimeout(resolve, 160));
    if (scenario === 'error')
      throw new Error('Mock 영향 경로 조회 실패 · 다시 시도해 주세요.');
    return createMockImpact(companyId, issueId, scenario);
  }

  return call<Impact>(impactUrl(companyId, issueId), 'GET', undefined, {
    skipAuth: true,
  });
}
