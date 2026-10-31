import { call } from '@/apis/auth/ApiService';
import type {
  BriefingEdition,
  BriefingGraphBasis,
  BriefingItemDetail,
  BriefingResponse,
  BriefingRecap,
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

/** D-BRF-01·02: 회차의 고정 문안·정확 인용·원문 맥락을 버튼을 펼칠 때 조회한다. */
export async function getBriefingItemDetail(
  roundId: string,
  eventId: string,
  expectedGraphVersion?: string | null,
) {
  const detail = await call<BriefingItemDetail>(
    `/api/v1/briefings/${encodeURIComponent(roundId)}/items/${encodeURIComponent(eventId)}`,
    'GET',
    undefined,
    { skipAuth: true },
  );
  if (
    detail.roundId !== roundId ||
    detail.eventId !== eventId ||
    (expectedGraphVersion !== undefined &&
      detail.metadata.graphVersion !== expectedGraphVersion)
  )
    throw new Error('요청한 브리핑 회차·이슈·버전과 응답이 일치하지 않습니다.');
  return detail;
}

/** getPersonalizedBriefing (FS036): 같은 발행본에 본인 기준 기업과 겹치는 기업(matchedCompanyIds)을 표시한다. 회원 본인만. */
export function getPersonalizedBriefing(roundId: string) {
  return call<BriefingResponse>(
    `/api/v1/briefings/${encodeURIComponent(roundId)}/personalized`,
    'GET',
  );
}

/** D-BRF-01·02: 현재 회차가 고정한 과거 발행본만 복기한다. */
export async function getBriefingRecap(round: BriefingResponse) {
  const recap = await call<BriefingRecap>(
    `/api/v1/briefings/${encodeURIComponent(round.id)}/recap`,
    'GET',
    undefined,
    { skipAuth: true },
  );
  if (
    recap.roundId !== round.id ||
    recap.graphVersion !== round.graphVersion ||
    Date.parse(recap.dataAsOf ?? '') !== Date.parse(round.dataAsOf ?? '')
  )
    throw new Error(
      '요청한 회차·버전·기준 시각과 복기 응답이 일치하지 않습니다.',
    );
  if (recap.status === 'available') {
    const reference =
      round.edition === 'evening'
        ? round.sinceMorning
        : round.previousComparison;
    const expectedId =
      reference?.status === 'available'
        ? 'morningRoundId' in reference
          ? reference.morningRoundId
          : reference.previousRoundId
        : null;
    const previous = recap.previous;
    if (
      !previous ||
      previous.id !== expectedId ||
      previous.id === round.id ||
      previous.status !== 'published' ||
      previous.corrections.length > 0 ||
      !previous.items.length ||
      !(Date.parse(previous.dataAsOf ?? '') < Date.parse(round.dataAsOf ?? ''))
    )
      throw new Error('고정된 이전 발행본과 복기 응답이 일치하지 않습니다.');
  } else if (recap.previous !== null) {
    throw new Error('제공할 수 없는 과거 내용이 포함돼 있습니다.');
  }
  return recap;
}

/** FS036: independent selection from the round's whole qualified candidate pool. */
export function getPersonalizedBriefingIssues(roundId: string) {
  return call<import('@/types/personalBriefing').PersonalBriefingSelection>(
    `/api/v1/briefings/${encodeURIComponent(roundId)}/personalized/issues`,
    'GET',
  );
}
