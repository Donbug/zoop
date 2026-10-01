// 기업 패널의 관련 이슈 → 영향 경로(명세 FS022, D03). 지도 데이터(승인된 관계)만으로 계산한다.
//  - 경로: 선택 기업에서 그 사건까지의 최단 연결(graph-path와 같은 규칙: 사건 공유 파생선은 쓰지 않는다).
//    1단계면 직접 연결(직접 관련·구조적 관련), 그 이상이면 중간 사건·기업을 거친 간접 연결이다.
//  - 함께 연결된 기업: 그 사건에 직접 관련·구조적 관련으로 이어진 다른 기업.
//  - 데이터에 없는 산업·제품 단계나 인과 관계는 만들지 않는다. 경로가 없으면 null이고 지도에 아무 선도 더하지 않는다.
// 주소: ?impact=<기업>,<사건>
import type { Schemas } from "@/api/client";
import { shortestPath, type GraphPath } from "./graph-path";

export interface ImpactPath {
  companyId: string;
  issueId: string;
  /** 선택 기업 → 사건 경로. 이어지지 않으면 null. */
  route: GraphPath | null;
  /** 경로 단계(경로 순서) */
  steps: { edge: Schemas["GraphEdge"]; from: string; to: string }[];
  /** 같은 사건에 이어진 다른 기업(직접 관련 먼저) */
  others: { edge: Schemas["GraphEdge"]; companyId: string }[];
  /** 지도 강조용: 경로 + 함께 연결된 기업과 그 선. from = 기업, to = 사건 */
  highlight: GraphPath | null;
}

const COMPANY_LINK = new Set(["INVOLVES", "STRUCTURALLY_RELATED_TO"]);

export function impactPath(nodes: Schemas["GraphNode"][], edges: Schemas["GraphEdge"][], companyId: string, issueId: string): ImpactPath {
  const route = shortestPath(nodes, edges, companyId, issueId);
  const edgeById = new Map(edges.map((e) => [e.id, e]));
  const steps = route
    ? route.edgeIds.map((id, i) => ({ edge: edgeById.get(id)!, from: route.nodeIds[i]!, to: route.nodeIds[i + 1]! }))
    : [];
  const companyIds = new Set(nodes.filter((n) => n.kind === "company").map((n) => n.id));
  const others = edges
    .filter((e) => COMPANY_LINK.has(e.relationType) && (e.source === issueId || e.target === issueId))
    .map((edge) => ({ edge, companyId: edge.source === issueId ? edge.target : edge.source }))
    .filter((o) => o.companyId !== companyId && companyIds.has(o.companyId))
    .sort((a, b) => (a.edge.relationType === b.edge.relationType ? 0 : a.edge.relationType === "INVOLVES" ? -1 : 1));
  const highlight = route
    ? {
        from: companyId,
        to: issueId,
        nodeIds: [...route.nodeIds, ...others.map((o) => o.companyId)],
        edgeIds: [...route.edgeIds, ...others.map((o) => o.edge.id)],
      }
    : null;
  return { companyId, issueId, route, steps, others, highlight };
}
