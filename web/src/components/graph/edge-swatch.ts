import type { GraphEdge } from '@/types/map/graph';

// D-GRP-01 범례와 경로 단계(D-GRP-07)가 같은 선 견본을 쓴다. graph-model.ts의 선 모양과 맞춘다:
// 후속 사건만 진하게(화살표 없음은 견본에서 생략), 사건 공유만 점선, 구조적 관련은 흐리게.
export function edgeSwatchClass(type: GraphEdge['relationType'] | string) {
  return `legend-line ${
    type === 'FOLLOWS'
      ? 'follows'
      : type === 'SHARES_ISSUE'
        ? 'dashed'
        : type === 'STRUCTURALLY_RELATED_TO'
          ? 'opacity-50'
          : ''
  }`;
}
