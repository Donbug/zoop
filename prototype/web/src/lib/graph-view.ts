// 지도 표시 규칙(데이터는 그대로 두고 보이는 방식만 바꾼다). 캔버스·범례·상세 패널이 같이 쓴다.
//  - 연결 없는 사건 묶음(G1): 그래프에서 간선이 하나도 없는 사건은 묶음 노드 하나로 모은다. FOLLOWS만 있어도 연결된 것.
//  - 포커스(G2): 한 노드의 n단계 이웃만 남긴다. 주소 ?focus=<id>&hops=1|2
//  - 범례 필터(G5): 노드 종류·관계 유형별 표시 켜기/끄기(재배치 없음). 묶음은 '사건'을 따른다.
//  - 근거 연동(G4): 근거 창의 인용 하나를 지도에서 강조한다.
import type { Schemas } from "@/api/client";
import type { RelationType } from "./labels";

export const ISOLATED_BUNDLE_ID = "bundle:isolated";

export type FocusHops = 1 | 2;
export interface GraphFocus {
  id: string;
  hops: FocusHops;
}

/** 범례 토글 단위: 노드 종류 + 관계 유형 */
export type LegendKey = "company" | "issue" | RelationType;

/** 근거 창에서 `지도에서 보기`를 누른 인용. 이 근거 id를 가진 간선이 없으면 사건 노드만 강조한다. */
export interface EvidenceHighlight {
  evidenceId: string;
  issueId?: string;
}

/** 간선이 하나도 없는 사건(그래프에 보이는 순서 그대로). */
export function isolatedIssues(nodes: Schemas["GraphNode"][], edges: Schemas["GraphEdge"][]) {
  const linked = new Set<string>();
  for (const edge of edges) {
    linked.add(edge.source);
    linked.add(edge.target);
  }
  return nodes.filter((n) => n.kind === "issue" && !linked.has(n.id));
}

export function isolatedBundleLabel(count: number) {
  return `연결 없는 사건 ${count}건`;
}
