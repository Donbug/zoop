import { adminCall } from '@/apis/admin/auth';
import { ApiError } from '@/apis/auth/ApiService';
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

/** getPipelineOverview: 후보 판정 수·검수 대기·공개 버전·분석 작업 요약 */
export function getPipelineOverview() {
  return adminCall<PipelineOverview>(`${PIPELINE}/overview`, 'GET');
}

/** listAnalysisCandidates: 서명된 불투명 커서. 커서는 같은 조건에서만 유효하다. */
export function listAnalysisCandidates(
  filters: CandidateFilters,
  cursor?: string,
) {
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
export function getAnalysisCandidate(candidateId: string) {
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
  const result = await adminCall<CandidateDecisionResponse>(
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
