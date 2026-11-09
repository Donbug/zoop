import { adminCall } from '@/apis/admin/auth';
import { ApiError } from '@/apis/auth/ApiService';
import {
  mockDecideCandidate,
  mockGetCandidate,
  mockListCandidates,
  withMockCandidateCounts,
} from '@/mocks/admin/candidates';
import type {
  CandidateDecisionRequest,
  CandidateDecisionResponse,
  CandidateDetail,
  CandidateFilters,
  CandidateList,
  PipelineOverview,
} from '@/types/admin/pipeline';

// A-ADM-03 이슈 관제 개요와 검수 후보 (FS058·FS059·FS067-01·FS067-02).
// 후보 결정(decideAnalysisCandidate)은 관리자 CSRF·Idempotency-Key가 필요하고, 사유는 감사 로그에 남는다.

const PIPELINE = '/api/v1/admin/pipeline';

/**
 * 개발 서버에서 지도 목업을 쓰는 동안(VITE_GRAPH_DATA_SOURCE≠api) 후보 목록·상세·결정도 지도 목업 이슈로 만든 합성 후보를 쓴다.
 * 개요는 실제 API를 읽고 후보 판정 수만 목업과 맞춘다. 배포 빌드와 테스트에서는 항상 실제 API다.
 */
export function usesCandidateMock() {
  return (
    import.meta.env.DEV &&
    import.meta.env.MODE !== 'test' &&
    import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api'
  );
}

/** getPipelineOverview: 후보 판정 수·검수 대기·공개 버전·분석 작업 요약 */
export async function getPipelineOverview() {
  const overview = await adminCall<PipelineOverview>(
    `${PIPELINE}/overview`,
    'GET',
  );
  return usesCandidateMock() ? withMockCandidateCounts(overview) : overview;
}

/** listAnalysisCandidates: 서명된 불투명 커서. 커서는 같은 조건에서만 유효하다. */
export function listAnalysisCandidates(
  filters: CandidateFilters,
  cursor?: string,
) {
  if (usesCandidateMock())
    return Promise.resolve(mockListCandidates(filters, cursor));
  const query = new URLSearchParams();
  if (filters.status) query.set('status', filters.status);
  if (filters.decision) query.set('decision', filters.decision);
  if (filters.active !== undefined) query.set('active', String(filters.active));
  if (filters.published !== undefined)
    query.set('published', String(filters.published));
  if (filters.rule !== undefined) query.set('rule', String(filters.rule));
  if (filters.q) query.set('q', filters.q);
  if (cursor) query.set('cursor', cursor);
  const suffix = query.size ? `?${query}` : '';
  return adminCall<CandidateList>(`${PIPELINE}/candidates${suffix}`, 'GET');
}

/** getAnalysisCandidate: 원문 인용·관계·검증 판정·검수 이력 */
export async function getAnalysisCandidate(candidateId: string) {
  if (usesCandidateMock()) return mockGetCandidate(candidateId);
  return adminCall<CandidateDetail>(
    `${PIPELINE}/candidates/${encodeURIComponent(candidateId)}`,
    'GET',
  );
}

/**
 * decideAnalysisCandidate: 관계 하나를 승인(allow, HOLD 최종 승인)하거나 거부한다.
 * 상세에서 본 revision·AI 원천과 지금 값이 다르면 409로 거절된다.
 */
export async function decideAnalysisCandidate(
  candidateId: string,
  request: CandidateDecisionRequest,
  idempotencyKey: string,
) {
  const result = usesCandidateMock()
    ? mockDecideCandidate(candidateId, request)
    : await adminCall<CandidateDecisionResponse>(
        `${PIPELINE}/candidates/${encodeURIComponent(candidateId)}/decision`,
        'POST',
        request,
        { 'Idempotency-Key': idempotencyKey },
      );
  const expected = request.decision === 'allow' ? 'approved' : 'rejected';
  if (result.candidateId !== candidateId || result.decision !== expected)
    throw new ApiError(
      200,
      'INVALID_RESPONSE',
      '요청한 후보 결정과 응답이 일치하지 않습니다.',
    );
  return result;
}
