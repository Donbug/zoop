// FS017·FS019·FS026 개인화(내 종목) 지도 안의 기준 필터: 전체 · 보유 · 관심.
//  - 그래프 모드(시장 전체/내 종목)와 따로 관리한다. 같은 탭 세션 동안 마지막 필터를 기억하고(새로고침·모드 왕복 복원),
//    새 탭(새 세션)·로그아웃 뒤에는 전체로 시작한다.
//  - 전체 = BFF 개인화 응답 그대로(보유 + 관심을 함께 기준으로 둔 연결 요소).
//  - 보유·관심 = 그 응답 안에서 기준 기업(노드의 holding/watch 표시)과, 기준 기업에 직접 이어진 사건(INVOLVES·구조적 관련),
//    그 사건에 함께 이어진 관련 기업, 그 사건의 앞뒤 사건(FOLLOWS, 기업은 더 끌어오지 않음)만 남긴다(FS017 ⑨).
//    보유·관심 둘 다인 기업은 두 필터 모두의 기준이다. 연결 요소 전체를 쓰면 실제 데이터에서 보유·관심이 같은 지도가 되므로
//    한 단계로 좁힌다(프로토타입 가정: 깊이 1단계).
//  - 응답을 다시 받지 않고 화면에서 거르므로 늦게 온 이전 필터 응답이 생길 수 없다(FS017 ⑪).
import type { Schemas } from "@/api/client";
import { parsePathParam } from "@/lib/graph-path";
import { ISOLATED_BUNDLE_ID } from "@/lib/graph-view";

type Graph = Schemas["GraphResponse"];

export type PersonalFilter = "all" | "holding" | "watch";

export const personalFilterLabel: Record<PersonalFilter, string> = { all: "전체", holding: "보유", watch: "관심" };

/** 사건–기업 연결(직접·구조적). 파생(SHARES_ISSUE)과 사건–사건(FOLLOWS)은 기준을 넓히지 않는다. */
const COMPANY_LINKS: Partial<Record<string, true>> = { INVOLVES: true, STRUCTURALLY_RELATED_TO: true };

export interface FilteredGraph {
  graph: Graph;
  /** 이 필터의 기준 기업 수(지도에 있는 보유/관심 기업). 전체는 보유 ∪ 관심 */
  baseCount: number;
}

/** 개인화 응답을 필터로 거른다. 전체면 같은 객체를 그대로 돌려준다(배치를 다시 하지 않게). */
export function filterPersonalGraph(graph: Graph, filter: PersonalFilter): FilteredGraph {
  const isBase = (n: Schemas["GraphNode"]) =>
    n.kind === "company" && (filter === "holding" ? Boolean(n.holding) : filter === "watch" ? Boolean(n.watch) : Boolean(n.holding || n.watch));
  const base = new Set(graph.nodes.filter(isBase).map((n) => n.id));
  if (filter === "all") return { graph, baseCount: base.size };

  const kind = new Map(graph.nodes.map((n) => [n.id, n.kind]));
  const companyLinks = graph.edges.filter((e) => COMPANY_LINKS[e.relationType]);
  const issues = new Set<string>();
  for (const e of companyLinks) {
    if (base.has(e.source) && kind.get(e.target) === "issue") issues.add(e.target);
    if (base.has(e.target) && kind.get(e.source) === "issue") issues.add(e.source);
  }
  const keep = new Set([...base, ...issues]);
  for (const e of companyLinks) {
    if (issues.has(e.source) && kind.get(e.target) === "company") keep.add(e.target);
    if (issues.has(e.target) && kind.get(e.source) === "company") keep.add(e.source);
  }
  for (const e of graph.edges) {
    if (e.relationType !== "FOLLOWS") continue;
    if (issues.has(e.source)) keep.add(e.target);
    if (issues.has(e.target)) keep.add(e.source);
  }
  const nodes = graph.nodes.filter((n) => keep.has(n.id));
  // BFF와 같은 규칙: 양 끝이 남은 선만, 파생 선은 거쳐 간 사건 하나 이상이 남았을 때만.
  const edges = graph.edges.filter((e) => keep.has(e.source) && keep.has(e.target) && (!e.derived || e.via.some((v) => keep.has(v))));
  return {
    graph: {
      ...graph,
      nodes,
      edges,
      metadata: {
        ...graph.metadata,
        focusCompanyIds: graph.metadata.focusCompanyIds.filter((id) => base.has(id)),
        emptyReason: edges.length === 0 ? "no_related_issues" : null,
      },
    },
    baseCount: base.size,
  };
}

/** 주소의 선택·포커스·경로·영향 경로 중 이 지도에 있는 것만 남긴다. 빠진 것이 있으면 dropped. */
export function retainTargets(params: URLSearchParams, graph: Graph): { kept: URLSearchParams; dropped: boolean } {
  const inMap = (id: string) => graph.nodes.some((n) => n.id === id);
  const kept = new URLSearchParams();
  let dropped = false;
  const select = params.get("select");
  if (select) {
    const id = select.replace(/^(edge|node):/, "");
    if (select.startsWith("edge:") ? graph.edges.some((e) => e.id === id) : id === ISOLATED_BUNDLE_ID || inMap(id)) kept.set("select", select);
    else dropped = true;
  }
  const focusId = params.get("focus");
  if (focusId && inMap(focusId)) {
    kept.set("focus", focusId);
    kept.set("hops", params.get("hops") ?? "1");
  } else if (focusId) dropped = true;
  for (const key of ["path", "impact"] as const) {
    const pair = parsePathParam(params.get(key));
    if (pair && pair.every(inMap)) kept.set(key, pair.join(","));
    else if (pair) dropped = true;
  }
  return { kept, dropped };
}

const KEY = "zoop:personal-filter";

export function readPersonalFilter(): PersonalFilter {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw === "holding" || raw === "watch" ? raw : "all";
  } catch {
    return "all";
  }
}

/** 같은 탭 세션의 마지막 필터를 기억한다. 전체는 지워서 기본값과 같게 둔다(로그아웃도 이 값으로 초기화). */
export function savePersonalFilter(filter: PersonalFilter): void {
  try {
    if (filter === "all") sessionStorage.removeItem(KEY);
    else sessionStorage.setItem(KEY, filter);
  } catch {
    // 저장소를 쓸 수 없으면 새로고침 뒤 전체로 시작한다.
  }
}
