import { adminCall } from '@/apis/admin/auth';
import type {
  AdminRound,
  AiUsage,
  AiUsageWindow,
  Correction,
  CorrectionRequest,
  RoundDetail,
  RoundList,
  SuspensionAction,
} from '@/types/admin/briefings';

// A-ADM-04 브리핑 운영 · A-ADM-04b AI 사용량.
// 쓰기 요청(재처리·정정·제공 중단/재개)은 관리자 CSRF와 Idempotency-Key가 필요하다.
// 같은 요청을 다시 보낼 때는 같은 키를 써서 응답만 유실돼도 중복 처리되지 않게 한다.

const BRIEFINGS = '/api/v1/admin/briefings';
const round = (roundId: string) =>
  `${BRIEFINGS}/${encodeURIComponent(roundId)}`;
const idempotent = (key: string) => ({ 'Idempotency-Key': key });

/** listAdminBriefingRounds: 회차 운영 상태(불투명 커서) */
export function listAdminBriefingRounds(cursor?: string) {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
  return adminCall<RoundList>(`${BRIEFINGS}${query}`, 'GET');
}

/** getAdminBriefingRound: 생성·검증·발행 상태, 발행 원문, 정정, 처리 기록 */
export function getAdminBriefingRound(roundId: string) {
  return adminCall<RoundDetail>(round(roundId), 'GET');
}

/** reprocessBriefingRound: 미발행(지연·실패) 회차만 다시 처리한다. 202 */
export function reprocessBriefingRound(
  roundId: string,
  reason: string,
  idempotencyKey: string,
) {
  return adminCall<AdminRound>(
    `${round(roundId)}/reprocess`,
    'POST',
    { reason },
    idempotent(idempotencyKey),
  );
}

/** appendBriefingCorrection: 발행 원문을 유지하고 정정을 덧붙인다. 201 */
export function appendBriefingCorrection(
  roundId: string,
  request: CorrectionRequest,
  idempotencyKey: string,
) {
  return adminCall<Correction>(
    `${round(roundId)}/corrections`,
    'POST',
    request,
    idempotent(idempotencyKey),
  );
}

/** setBriefingSuspension: 발행 회차의 제공 중단·재개. 발행 이력은 보존된다. */
export function setBriefingSuspension(
  roundId: string,
  action: SuspensionAction,
  reason: string,
  idempotencyKey: string,
) {
  return adminCall<AdminRound>(
    `${round(roundId)}/suspension`,
    'POST',
    { action, reason },
    idempotent(idempotencyKey),
  );
}

/** getAiUsage: 기능별 요청·실제 모델 호출·재시도·처리 시간·사용량·비용(실제/추정 구분) */
export function getAiUsage(window: AiUsageWindow) {
  return adminCall<AiUsage>(`/api/v1/admin/ai-usage?window=${window}`, 'GET');
}
