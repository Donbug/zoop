import { call } from '@/apis/auth/ApiService';
import type { RelationDetail } from '@/types/map/relation';
import { snapshotUrl, assertSnapshot } from './snapshot';
import {
  createMockRelation,
  type RelationMockScenario,
} from '@/mocks/relations/fixture';
import type { EventContext } from '@/types/map/event';

// D-GRP-04 연결선 상세(getCompanyRelation, #217). 지도와 같은 공개 버전·기준 시점으로 조회한다.
// 개발 목업 모드(VITE_GRAPH_DATA_SOURCE≠api)에서만 합성 자료를 쓴다(graph.ts의 usesGraphMock과 같은 조건).
const usesRelationMock =
  import.meta.env.DEV && import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api';
export async function getRelation(id: string, context: EventContext = {}) {
  if (context.round || !usesRelationMock) {
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
