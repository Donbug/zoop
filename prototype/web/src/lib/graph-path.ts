// 두 기업 사이 경로(G6). 지도 데이터 전체(범례로 숨긴 것 포함)에서 Cytoscape 내장 aStar로 최단 경로를 찾는다.
//  - 방향은 무시한다(사건 → 기업 방향 선도 거꾸로 따라간다).
//  - 파생 선(사건 공유, derived)은 쓰지 않는다. 실제 사건을 거치는 경로만 보여 주기 위해서다.
//  - 연결 없는 사건 묶음은 선이 없으므로 경로에 들어오지 않는다.
// 주소: ?path=<기업A>,<기업B>
import cytoscape from "cytoscape";
import type { Schemas } from "@/api/client";

export interface GraphPath {
  from: string;
  to: string;
  /** 경로 순서대로의 노드 id(양 끝 포함) */
  nodeIds: string[];
  /** 경로 순서대로의 선 id. 길이가 단계 수다. */
  edgeIds: string[];
}

/** `?path=` 값 → 두 기업 id. 형식이 맞지 않거나 같은 기업이면 null. */
export function parsePathParam(value: string | null): [string, string] | null {
  if (!value) return null;
  const parts = value.split(",");
  if (parts.length !== 2 || !parts[0] || !parts[1] || parts[0] === parts[1]) return null;
  return [parts[0], parts[1]];
}

/** 최단 경로. 이어지지 않으면 null. 선 가중치는 모두 1(단계 수 최소). */
export function shortestPath(nodes: Schemas["GraphNode"][], edges: Schemas["GraphEdge"][], from: string, to: string): GraphPath | null {
  const ids = new Set(nodes.map((n) => n.id));
  if (!ids.has(from) || !ids.has(to) || from === to) return null;
  const cy = cytoscape({
    headless: true,
    styleEnabled: false,
    elements: [
      ...nodes.map((n) => ({ group: "nodes" as const, data: { id: n.id } })),
      ...edges
        .filter((e) => !e.derived && e.relationType !== "SHARES_ISSUE" && ids.has(e.source) && ids.has(e.target))
        .map((e) => ({ group: "edges" as const, data: { id: e.id, source: e.source, target: e.target } })),
    ],
  });
  const result = cy.elements().aStar({ root: cy.getElementById(from), goal: cy.getElementById(to), directed: false });
  const path = result.found
    ? { from, to, nodeIds: result.path.nodes().map((n) => n.id()), edgeIds: result.path.edges().map((e) => e.id()) }
    : null;
  cy.destroy();
  return path;
}
