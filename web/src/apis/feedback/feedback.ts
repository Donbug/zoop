import { useAuthStore } from '@/stores/useAuthStore';
import { call } from '@/apis/auth/ApiService';
import type {
  FeedbackFeature,
  FeedbackItem,
  FeedbackList,
  FeedbackVote,
} from '@/types/feedback';

// FS066-01 평가. 회원 본인만 조회·저장한다(쓰기는 회원 CSRF).

/** getMyFeedback: 여러 대상의 내 유효 평가를 한 번에 읽는다(targetIds는 쉼표로 잇는다). */
export async function getMyFeedback(
  feature: FeedbackFeature,
  targetIds: string[],
): Promise<FeedbackList> {
  const revision = useAuthStore.getState().sessionRevision;
  const items: FeedbackItem[] = [];
  const seen = new Set<string>();
  const targets = new Set(targetIds);
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({
      feature,
      targetIds: targetIds.join(','),
    });
    if (cursor) query.set('cursor', cursor);
    const page = await call<FeedbackList>(`/api/v1/feedback?${query}`, 'GET');
    if (useAuthStore.getState().sessionRevision !== revision)
      throw new Error('계정이 변경됐어요.');
    for (const item of page.items) {
      if (
        item.feature !== feature ||
        !targets.has(item.targetId) ||
        items.some((old) => old.targetId === item.targetId)
      )
        throw new Error('내 평가 응답을 확인하지 못했어요.');
      items.push(item);
    }
    cursor = page.nextCursor;
    if (cursor && seen.has(cursor))
      throw new Error('내 평가 페이지를 확인하지 못했어요.');
    if (cursor) seen.add(cursor);
  } while (cursor);
  return { items, nextCursor: null };
}

/** setFeedback: 원하는 최종 상태를 저장한다. none은 평가 취소다. */
export function setFeedback(vote: FeedbackVote) {
  return call<FeedbackItem>('/api/v1/feedback', 'PUT', vote);
}
