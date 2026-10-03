// FS017·FS026 개인화 필터(전체 · 보유 · 관심)의 순수 파생 규칙: 기준 기업 + 직접 이어진 사건 + 그 사건의 관련 기업 + 앞뒤 사건.
import { describe, expect, test } from "vitest";
import type { Schemas } from "@/api/client";
import { ISOLATED_BUNDLE_ID } from "@/lib/graph-view";
import { filterPersonalGraph, readPersonalFilter, retainTargets, savePersonalFilter } from "@/lib/personal-filter";

type Node = Schemas["GraphNode"];
type Edge = Schemas["GraphEdge"];

const node = (id: string, kind: Node["kind"], marks: { holding?: boolean; watch?: boolean } = {}): Node => ({
  id,
  kind,
  label: id,
  isFocus: false,
  holding: marks.holding ?? false,
  watch: marks.watch ?? false,
  brandColor: null,
  logoUrl: null,
  eventTime: null,
  timePrecision: null,
  action: null,
  target: null,
  evidenceCount: null,
});

const edge = (source: string, target: string, relationType: Edge["relationType"] = "INVOLVES", via: string[] = []): Edge => ({
  id: `${source}-${relationType}-${target}`,
  source,
  target,
  relationType,
  role: null,
  summary: "관련",
  assertionStatus: null,
  derived: relationType === "SHARES_ISSUE",
  via,
  evidenceIds: [],
});

const graphOf = (nodes: Node[], edges: Edge[]): Schemas["GraphResponse"] => ({
  nodes,
  edges,
  metadata: {
    datasetKind: "synthetic-preview",
    source: "test",
    asOf: "2026-10-03T00:00:00+00:00",
    sourceMode: "snapshot",
    synthetic: true,
    generatedBy: null,
    graphVersion: "v1",
    mode: "personal",
    truncated: false,
    emptyReason: null,
    focusCompanyIds: nodes.filter((n) => n.holding || n.watch).map((n) => n.id),
    depth: null,
    limit: 500,
  },
});

// 보유 H, 관심 W, 둘 다 B. R1은 H·B의 사건에 함께 나온 관련 기업, R2는 R1을 거쳐야 닿는 두 단계 밖 기업,
// X는 H 사건의 후속 사건에만 나오는 기업.
const personal = graphOf(
  [
    node("H", "company", { holding: true }),
    node("W", "company", { watch: true }),
    node("B", "company", { holding: true, watch: true }),
    node("R1", "company"),
    node("R2", "company"),
    node("X", "company"),
    node("iH", "issue"),
    node("iW", "issue"),
    node("iB", "issue"),
    node("iFollow", "issue"),
    node("iFar", "issue"),
  ],
  [
    edge("H", "iH"),
    edge("R1", "iH"),
    edge("W", "iW"),
    edge("B", "iB"),
    edge("R1", "iB"),
    edge("X", "iFollow"),
    edge("R1", "iFar"),
    edge("R2", "iFar"),
    edge("iH", "iFollow", "FOLLOWS"),
    edge("H", "R1", "SHARES_ISSUE", ["iH"]),
    edge("R1", "R2", "SHARES_ISSUE", ["iFar"]),
  ],
);

const ids = (items: { id: string }[]) => items.map((i) => i.id).sort();

describe("filterPersonalGraph", () => {
  test("전체는 받은 개인화 지도를 그대로(같은 객체로) 돌려 다시 배치하지 않는다", () => {
    const result = filterPersonalGraph(personal, "all");
    expect(result.graph).toBe(personal);
    expect(result.baseCount).toBe(3);
  });

  test("보유는 보유 기업과 직접 이어진 사건, 그 사건의 관련 기업, 앞뒤 사건만 남기고 두 단계 밖은 뺀다", () => {
    const { graph, baseCount } = filterPersonalGraph(personal, "holding");
    expect(baseCount).toBe(2);
    expect(ids(graph.nodes)).toEqual(["B", "H", "R1", "iB", "iFollow", "iH"]);
    // 후속 사건은 붙지만 그 사건의 기업(X)은 끌어오지 않는다. 양 끝이 남은 선만, 파생 선은 거친 사건이 남았을 때만.
    expect(ids(graph.edges)).toEqual(["B-INVOLVES-iB", "H-INVOLVES-iH", "H-SHARES_ISSUE-R1", "R1-INVOLVES-iB", "R1-INVOLVES-iH", "iH-FOLLOWS-iFollow"]);
    expect(graph.metadata.focusCompanyIds.sort()).toEqual(["B", "H"]);
    expect(graph.metadata.emptyReason).toBeNull();
  });

  test("보유·관심 둘 다인 기업은 두 필터 모두에 하나의 노드로 나오고 표시를 그대로 지닌다", () => {
    const holding = filterPersonalGraph(personal, "holding").graph.nodes.filter((n) => n.id === "B");
    const watch = filterPersonalGraph(personal, "watch").graph.nodes.filter((n) => n.id === "B");
    expect(holding).toEqual([personal.nodes[2]]);
    expect(watch).toEqual([personal.nodes[2]]);
    expect(ids(filterPersonalGraph(personal, "watch").graph.nodes)).toEqual(["B", "R1", "W", "iB", "iW"]);
  });

  test("고른 범위의 기준 기업이 0개면 빈 지도와 기준 0을 돌려준다(오류가 아니다)", () => {
    const noWatch = graphOf(
      personal.nodes.map((n) => ({ ...n, watch: false })),
      personal.edges,
    );
    const { graph, baseCount } = filterPersonalGraph(noWatch, "watch");
    expect(baseCount).toBe(0);
    expect(graph.nodes).toEqual([]);
    expect(graph.edges).toEqual([]);
    expect(graph.metadata.emptyReason).toBe("no_related_issues");
  });

  test("기준 기업은 있지만 연결된 사건이 없으면 기준 기업만 남기고 관계 0건으로 표시한다", () => {
    const lonely = graphOf([node("H", "company", { holding: true }), node("W", "company", { watch: true }), node("iW", "issue")], [edge("W", "iW")]);
    const { graph, baseCount } = filterPersonalGraph(lonely, "holding");
    expect(baseCount).toBe(1);
    expect(ids(graph.nodes)).toEqual(["H"]);
    expect(graph.metadata.emptyReason).toBe("no_related_issues");
  });
});

describe("retainTargets", () => {
  const holding = filterPersonalGraph(personal, "holding").graph;

  test("필터에서 빠진 노드를 고르고 있었으면 선택을 풀고 알린다", () => {
    const { kept, dropped } = retainTargets(new URLSearchParams("mode=personal&select=node:W"), holding);
    expect(dropped).toBe(true);
    expect(kept.has("select")).toBe(false);
  });

  test("남은 대상(노드·선·묶음·포커스)은 그대로 두고, 한쪽 끝이 빠진 경로는 푼다", () => {
    const edgeKept = retainTargets(new URLSearchParams("select=edge:H-INVOLVES-iH&focus=H&hops=2"), holding);
    expect(edgeKept.dropped).toBe(false);
    expect(edgeKept.kept.toString()).toBe("select=edge%3AH-INVOLVES-iH&focus=H&hops=2");
    expect(retainTargets(new URLSearchParams(`select=node:${ISOLATED_BUNDLE_ID}`), holding).dropped).toBe(false);
    const path = retainTargets(new URLSearchParams("path=H,W"), holding);
    expect(path.dropped).toBe(true);
    expect(path.kept.has("path")).toBe(false);
  });
});

describe("세션 범위 저장", () => {
  test("같은 탭 세션의 마지막 필터를 읽고, 전체로 되돌리면 전체로 읽힌다", () => {
    expect(readPersonalFilter()).toBe("all");
    savePersonalFilter("watch");
    expect(readPersonalFilter()).toBe("watch");
    savePersonalFilter("all");
    expect(readPersonalFilter()).toBe("all");
  });
});
