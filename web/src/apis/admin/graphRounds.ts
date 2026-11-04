import { adminCall } from '@/apis/admin/auth';
import { ApiError } from '@/apis/auth/ApiService';
import type {
  GraphRound,
  GraphRoundDetail,
  GraphRoundList,
  GraphRoundStage,
} from '@/types/admin/graphRounds';

// A-ADM-03 그래프 정기 회차 (#55). 재시도·수동 시작은 관리자 CSRF·Idempotency-Key가 필요하고 감사 로그에 남는다.
// 두 명령은 회차 행만 바꾸고 실제 진행은 회차 실행기(writer)의 다음 바퀴가 한다. 살아 있는 실행기가 없으면 404다.

const ROUNDS = '/api/v1/admin/pipeline/rounds';

/** listGraphRounds: 최신 슬롯부터, 단계 필터, 불투명 커서 */
export function listGraphRounds(
  stage: GraphRoundStage | null,
  cursor?: string,
) {
  const query = new URLSearchParams();
  if (stage) query.set('stage', stage);
  if (cursor) query.set('cursor', cursor);
  const text = query.toString();
  return adminCall<GraphRoundList>(`${ROUNDS}${text ? `?${text}` : ''}`, 'GET');
}

/** getGraphRound: 회차 행과 이벤트 타임라인 */
export async function getGraphRound(roundId: string) {
  const result = await adminCall<GraphRoundDetail>(
    `${ROUNDS}/${encodeURIComponent(roundId)}`,
    'GET',
  );
  if (result.round.roundId !== roundId)
    throw new ApiError(
      200,
      'INVALID_RESPONSE',
      '요청한 회차와 응답이 일치하지 않습니다.',
    );
  return result;
}

/**
 * retryGraphRound: 실패한 회차를 같은 roundId로 멈춘 단계부터 다시 연다. 202.
 * 실패 상태가 아니면 409 REVISION_CONFLICT, 살아 있는 실행기가 없거나 모르는 회차면 404다.
 */
export async function retryGraphRound(roundId: string, idempotencyKey: string) {
  const result = await adminCall<GraphRound>(
    `${ROUNDS}/${encodeURIComponent(roundId)}/retry`,
    'POST',
    undefined,
    { 'Idempotency-Key': idempotencyKey },
  );
  if (result.roundId !== roundId)
    throw new ApiError(
      200,
      'INVALID_RESPONSE',
      '요청한 회차 재시도와 응답이 일치하지 않습니다.',
    );
  return result;
}

/**
 * startGraphRound: 지정한 슬롯(분 단위, ISO-8601) 또는 지금(slotAt null)의 회차를 만든다. 202.
 * 같은 슬롯이 이미 있으면 409 REVISION_CONFLICT, 형식 밖이면 422, 살아 있는 실행기가 없으면 404다.
 */
export async function startGraphRound(
  slotAt: string | null,
  idempotencyKey: string,
) {
  const result = await adminCall<GraphRound>(
    ROUNDS,
    'POST',
    { slotAt },
    { 'Idempotency-Key': idempotencyKey },
  );
  if (slotAt !== null && Date.parse(result.slotAt) !== Date.parse(slotAt))
    throw new ApiError(
      200,
      'INVALID_RESPONSE',
      '요청한 회차 시각과 응답이 일치하지 않습니다.',
    );
  return result;
}
