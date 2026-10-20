import { call } from '@/apis/auth/ApiService';
import type {
  BriefingEdition,
  BriefingGraphBasis,
  BriefingResponse,
  BriefingRoundsResponse,
} from '@/types/briefing';

// 공개 브리핑 조회. 모두 공개 GET이라 회원 세션 만료로 처리하지 않는다(skipAuth).

/** getBriefing (D-BRF-01·02 / FS033): 날짜를 빼면 그 회차 구분의 최신 회차를 받는다. */
export function getBriefing(date: string, edition: BriefingEdition) {
  const query = new URLSearchParams({ edition });
  if (date) query.set('date', date);
  return call<BriefingResponse>(
    `/api/v1/briefings?${query}`,
    'GET',
    undefined,
    { skipAuth: true },
  );
}

/** listBriefingRounds (FS035): 발행 회차 이력(최신 먼저, 불투명 커서) */
export function listBriefingRounds(cursor?: string) {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
  return call<BriefingRoundsResponse>(
    `/api/v1/briefings/rounds${query}`,
    'GET',
    undefined,
    { skipAuth: true },
  );
}

/** getBriefingGraphBasis (D-BRF-04 / FS032): 회차가 발행될 때의 그래프 기준 */
export async function getBriefingGraphBasis(roundId: string) {
  const basis = await call<BriefingGraphBasis>(
    `/api/v1/briefings/${encodeURIComponent(roundId)}/graph`,
    'GET',
    undefined,
    { skipAuth: true },
  );
  if (basis.roundId !== roundId)
    throw new Error('요청한 브리핑 회차와 응답이 일치하지 않습니다.');
  return basis;
}

/** getPersonalizedBriefing (FS036): 같은 발행본에 본인 기준 기업과 겹치는 기업(matchedCompanyIds)을 표시한다. 회원 본인만. */
export function getPersonalizedBriefing(roundId: string) {
  return call<BriefingResponse>(
    `/api/v1/briefings/${encodeURIComponent(roundId)}/personalized`,
    'GET',
  );
}
