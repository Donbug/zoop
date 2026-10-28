import { adminCall } from '@/apis/admin/auth';
import type {
  AnalysisJob,
  AnalyzePlanJobCreate,
  JobCreated,
  JobList,
} from '@/types/admin/jobs';

// A-ADM-03 작업 탭 (FS058·FS067). 다시 실행·취소는 관리자 CSRF·Idempotency-Key가 필요하고, 사유는 감사 로그에 남는다.
// 분석계획만 생성할 수 있다. 수집·재검증·반영 실행기는 별도 범위다.

const JOBS = '/api/v1/admin/jobs';

/** createAnalysisJob: 로컬 내구성 대기열 접수이며 AI 처리·검수·공개 완료가 아니다. */
export function createAnalyzePlan(
  request: AnalyzePlanJobCreate,
  idempotencyKey: string,
) {
  return adminCall<JobCreated>(JOBS, 'POST', request, {
    'Idempotency-Key': idempotencyKey,
  });
}

/** listAnalysisJobs: 요청 시각 최신 먼저. 실행 잠금·기사 처리 기준 시점·재시도 규칙을 함께 준다. 불투명 커서 */
export function listAnalysisJobs(cursor?: string) {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
  return adminCall<JobList>(`${JOBS}${query}`, 'GET');
}

/** getAnalysisJob: 실행 보고·사용량·오류를 포함한 작업 상세 */
export function getAnalysisJob(jobId: string) {
  return adminCall<AnalysisJob>(`${JOBS}/${encodeURIComponent(jobId)}`, 'GET');
}

/**
 * retryAnalysisJob: 재시도가 허용된(retry.allowed) 실패·취소 작업을 같은 입력의 새 작업으로 대기열에 넣는다.
 * 허용되지 않으면 409 REVISION_CONFLICT이고 아무것도 만들지 않는다.
 * analyze_plan은 고정된 S2·S3 ID로 이어서 처리하며 새 AI 실행 ID를 만들지 않는다.
 */
export function retryAnalysisJob(
  jobId: string,
  reason: string,
  idempotencyKey: string,
) {
  return adminCall<JobCreated>(
    `${JOBS}/${encodeURIComponent(jobId)}/retry`,
    'POST',
    { reason },
    { 'Idempotency-Key': idempotencyKey },
  );
}

/**
 * cancelAnalysisJob: 대기 중이면 바로 취소, 실행 중이면 취소를 요청한다. 원격 처리 중단·환불을 보장하지 않는다.
 * 이미 끝난(성공·실패) 작업은 409 REVISION_CONFLICT다.
 */
export function cancelAnalysisJob(
  jobId: string,
  reason: string,
  idempotencyKey: string,
) {
  return adminCall<AnalysisJob>(
    `${JOBS}/${encodeURIComponent(jobId)}/cancel`,
    'POST',
    { reason },
    { 'Idempotency-Key': idempotencyKey },
  );
}
