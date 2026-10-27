import { companies, directEdges, issues } from '@/mocks/graph/fixture';
import type { Impact } from '@/types/company/detail';

export type ImpactMockScenario =
  | 'success'
  | 'verified-impact'
  | 'structural'
  | 'structural-verified-impact'
  | 'empty'
  | 'error';

export function createMockImpact(
  companyId: string,
  issueId: string,
  scenario: ImpactMockScenario = 'success',
): Impact {
  const issue = issues.find((item) => item.id === issueId);
  const relation = directEdges.find(
    (edge) => edge.source === issueId && edge.target === companyId,
  );
  if (!issue || !companies.some((company) => company.id === companyId))
    throw new Error('선택한 기업 또는 사건을 찾을 수 없습니다.');
  const structural = scenario.startsWith('structural');
  const structuralStart = structural
    ? directEdges.find(
        (edge) => edge.source === issueId && edge.target !== companyId,
      )
    : undefined;
  const selected =
    scenario === 'empty'
      ? null
      : structural
        ? (structuralStart ?? null)
        : (relation ?? null);
  if (scenario !== 'empty' && !selected)
    throw new Error('선택한 기업과 사건의 연결을 찾을 수 없습니다.');
  const impactEvidenceIds = selected?.evidenceIds ?? [];
  const verified =
    scenario === 'verified-impact' || scenario === 'structural-verified-impact';
  const pathReason = structural
    ? '합성 구조 연결 예시'
    : selected?.summary || '직접 관련';

  return {
    companyId,
    issueId,
    pathStatus: selected ? 'available' : 'none',
    pathType: selected ? (structural ? 'structural' : 'direct') : null,
    edgeId: selected
      ? structural
        ? `mock-structural-${selected.id}`
        : selected.id
      : null,
    steps: selected
      ? [
          {
            id: issueId,
            kind: 'issue',
            reason: pathReason,
            evidenceIds: selected.evidenceIds,
          },
          {
            id: companyId,
            kind: 'company',
            reason: pathReason,
            evidenceIds: selected.evidenceIds,
          },
        ]
      : [],
    businessPath:
      !selected || !structural
        ? null
        : {
            status: 'complete',
            reason: null,
            companyIds: [selected.target, companyId],
            links: [
              {
                supplierCompanyId: selected.target,
                customerCompanyId: companyId,
                reason: 'SUPPLIES · 합성 재생 경로 예시',
                evidenceIds: impactEvidenceIds,
              },
            ],
          },
    impact: {
      status: verified ? 'available' : 'unavailable',
      reason: verified
        ? null
        : !selected
          ? 'no_public_path'
          : structural
            ? 'issue_impact_not_produced'
            : 'not_recorded',
      results: verified
        ? [
            {
              impactId: 'mock-impact-verified-1',
              status: 'verified',
              label: 'positive',
              evidenceIds: impactEvidenceIds,
              effects: {
                positive: impactEvidenceIds,
                negative: [],
                neutral: [],
                uncertain: [],
              },
            },
          ]
        : [],
    },
    metadata: {
      source: 'MOCK · ERD v6 기반 가상 데이터',
      asOf: '2026-10-06T03:41:00Z',
      graphVersion: 'mock-graph-v1',
      partial: false,
      failures: [],
    },
  };
}
