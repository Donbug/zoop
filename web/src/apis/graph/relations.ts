import { call } from '@/apis/auth/ApiService';
import type { RelationDetail } from '@/types/map/relation';
import { snapshotUrl, assertSnapshot } from './snapshot';
import {
  createMockRelation,
  type RelationMockScenario,
} from '@/mocks/relations/fixture';
import type { EventContext } from '@/types/map/event';

// WBS 6.6.24 is mock-only, including production builds. No HTTP fallback.
export async function getRelation(id: string, context: EventContext = {}) {
  if (context.round) {
    const relation = await call<RelationDetail>(
      snapshotUrl(`/api/v1/graph/edges/${encodeURIComponent(id)}`, context),
      'GET',
      undefined,
      { skipAuth: true },
    );
    if (relation.id !== id)
      throw new Error('요청한 연결선과 응답이 일치하지 않습니다.');
    assertSnapshot(relation.metadata, context);
    return relation;
  }
  await new Promise((resolve) => setTimeout(resolve, 220));
  return createMockRelation(
    id,
    context,
    import.meta.env.VITE_RELATION_MOCK_SCENARIO as
      RelationMockScenario | undefined,
  );
}
