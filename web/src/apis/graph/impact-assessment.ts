import { call } from '@/apis/auth/ApiService';
import { assertSnapshot, snapshotUrl } from '@/apis/graph/snapshot';
import type { EventContext } from '@/types/map/event';
import type { CompanyIssueImpactAssessment } from '@/types/map/impact-assessment';

export function impactAssessmentUrl(companyId: string, issueId: string) {
  return `/api/v1/companies/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/impact/assessment`;
}

export async function getCompanyIssueImpactAssessment(
  companyId: string,
  issueId: string,
  context: EventContext = {},
): Promise<CompanyIssueImpactAssessment> {
  const value = await call<CompanyIssueImpactAssessment>(
    snapshotUrl(impactAssessmentUrl(companyId, issueId), context),
    'GET',
    undefined,
    { skipAuth: true },
  );
  validateCompanyIssueImpactAssessment(value, companyId, issueId, context);
  return value;
}

export function validateCompanyIssueImpactAssessment(
  value: CompanyIssueImpactAssessment,
  companyId: string,
  issueId: string,
  context: EventContext,
) {
  const fail = () => {
    throw new Error(
      '요청한 기업·이슈·그래프 버전과 영향 평가가 일치하지 않습니다.',
    );
  };
  if (
    !value ||
    value.companyId !== companyId ||
    value.issueId !== issueId ||
    !['available', 'unavailable'].includes(value.status) ||
    ![
      null,
      'no_public_path',
      'not_recorded',
      'not_verified',
      'evidence_unavailable',
      'issue_impact_not_produced',
    ].includes(value.reason) ||
    value.metadata?.source !== 's3_issue_impacts' ||
    !Number.isFinite(Date.parse(value.metadata.asOf)) ||
    !Array.isArray(value.results)
  )
    fail();
  if (
    value.metadata.graphVersion !==
    (context.graphVersion ?? value.metadata.graphVersion)
  )
    fail();
  assertSnapshot(value.metadata, context);
  if (
    (value.status === 'available' &&
      (value.reason !== null || !value.results.length)) ||
    (value.status === 'unavailable' && (!value.reason || value.results.length))
  )
    fail();
  const ids = new Set<string>();
  for (const result of value.results) {
    if (
      !result.impactId ||
      ids.has(result.impactId) ||
      result.status !== 'verified' ||
      !['positive', 'negative', 'mixed', 'undetermined'].includes(
        result.label,
      ) ||
      !Array.isArray(result.evidenceIds) ||
      !result.evidenceIds.length ||
      !result.provenance ||
      !['collected', 'synthetic'].includes(result.provenance.sourceKind) ||
      !(
        (result.provenance.executionMode === 'live' &&
          result.provenance.recordingKind === 'provider') ||
        (result.provenance.executionMode === 'replay' &&
          result.provenance.recordingKind === 'authored-test')
      )
    )
      fail();
    ids.add(result.impactId);
    const sides = [
      result.effects?.positive,
      result.effects?.negative,
      result.effects?.neutral,
      result.effects?.uncertain,
    ];
    if (sides.some((side) => !Array.isArray(side))) fail();
    const flattened = sides.flat() as string[];
    if (
      new Set(flattened).size !== flattened.length ||
      flattened.length !== result.evidenceIds.length ||
      new Set(result.evidenceIds).size !== result.evidenceIds.length ||
      flattened.some((id) => !result.evidenceIds.includes(id))
    )
      fail();
  }
}
