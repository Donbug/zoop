import cytoscape from "cytoscape";
import { expect, test } from "vitest";
import { culledLabelIds, type LabelCandidate } from "@/components/domain/graph-declutter";
import { buildStyle, lodFor } from "@/components/domain/graph-style";

const box = { x1: 10, y1: 10, x2: 100, y2: 40 };
const candidate: LabelCandidate = { id: "issue", box, priority: 5, distance: 0, degree: 1, evidenceCount: 1 };

test("선택 대상 다음에 기업명, 주변 사건명, 선 요약 순으로 같은 공간을 선별한다", () => {
  const candidates = [
    { ...candidate, id: "edge", priority: 7 },
    candidate,
    { ...candidate, id: "company", priority: 1 },
    { ...candidate, id: "selected", priority: 0, box: { x1: 200, y1: 10, x2: 250, y2: 40 } },
  ];
  expect([...culledLabelIds(candidates, [])]).toEqual(["issue", "edge"]);
  expect([...culledLabelIds([...candidates].reverse(), [])]).toEqual(["issue", "edge"]);
});

test("칸 경계를 사이에 둔 2px 미만 간격도 충돌로 처리한다", () => {
  const left = { ...candidate, id: "left", priority: 1, box: { x1: 80, y1: 10, x2: 95.5, y2: 30 } };
  const right = { ...candidate, id: "right", box: { x1: 96.5, y1: 10, x2: 110, y2: 30 } };
  expect([...culledLabelIds([left, right], [])]).toEqual(["right"]);
  expect(culledLabelIds([left, { ...right, box: { ...right.box, x1: 97.5 } }], []).size).toBe(0);
});

test("자기 노드 경계는 제외하고 다른 노드 경계와 겹치는 이름만 숨긴다", () => {
  expect(culledLabelIds([candidate], [{ id: "issue", box }]).size).toBe(0);
  expect([...culledLabelIds([candidate], [{ id: "other", box }])]).toEqual(["issue"]);
  expect(culledLabelIds([{ ...candidate, priority: 0 }], [{ id: "other", box }]).size).toBe(0);
});

test("주변 사건은 가까운 이름을 우선하고 동률은 입력 순서와 무관하게 고른다", () => {
  const near = { ...candidate, id: "near", distance: 10 };
  const far = { ...candidate, id: "far", distance: 20, evidenceCount: 100 };
  expect([...culledLabelIds([far, near], [])]).toEqual(["far"]);
  const tied = [{ ...candidate, id: "b" }, { ...candidate, id: "a" }];
  expect([...culledLabelIds(tied, [])]).toEqual(["b"]);
  expect([...culledLabelIds([...tied].reverse(), [])]).toEqual(["b"]);
});

test("경로 스타일 소비자는 선별된 노드·간선 이름을 다시 노출하지 않는다", () => {
  // jsdom에는 캔버스 렌더러가 없다. 실제 공유 스타일의 label cascade만 headless Cytoscape로 검사한다.
  const style = buildStyle(false, lodFor(1, 1)).map((block) => {
    const properties = "style" in block ? block.style : block.css;
    const label = "label" in properties && typeof properties.label === "string" ? properties.label : undefined;
    return { selector: block.selector, style: label === undefined ? {} : { label } };
  });
  const cy = cytoscape({ headless: true, styleEnabled: true, style, elements: [
    { data: { id: "company", kind: "company", caption: "삼성전자" }, classes: "focused path" },
    { data: { id: "issue", kind: "issue", caption: "실제 사건 이름" }, classes: "path label-cull" },
    { data: { id: "edge", source: "issue", target: "company", summary: "실제 관계 요약" }, classes: "path label-cull" },
  ] });
  try {
    expect(cy.getElementById("company").style("label")).toBe("삼성전자");
    expect(cy.getElementById("issue").style("label")).toBe("");
    expect(cy.getElementById("edge").style("label")).toBe("");
    cy.elements(".label-cull").removeClass("label-cull");
    expect(cy.getElementById("issue").style("label")).toBe("실제 사건 이름");
    expect(cy.getElementById("edge").style("label")).toBe("실제 관계 요약");
  } finally {
    cy.destroy();
  }
});
