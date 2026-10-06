import cytoscape from "cytoscape";
import { expect, test } from "vitest";
import { focusPositions, type Positions } from "@/components/domain/graph-layout";

test("상세 요약 포커스는 지도 툴바 여백 대신 캔버스의 실제 공간을 사용한다", () => {
  const cy = cytoscape({ headless: true, elements: [
    { data: { id: "company", kind: "company" } },
    ...Array.from({ length: 12 }, (_, i) => ({ data: { id: `issue-${i}`, kind: "issue" } })),
    ...Array.from({ length: 12 }, (_, i) => ({ data: { id: `edge-${i}`, source: "company", target: `issue-${i}` } })),
  ] });
  const base: Positions = new Map(cy.nodes().map((node, i) => [node.id(), { x: Math.cos(i) * 100, y: Math.sin(i) * 100 }]));
  const focus = { id: "company", hops: 1 };
  const map = focusPositions(cy, focus, base, { width: 224, height: 234 });
  const detail = focusPositions(cy, focus, base, { width: 328, height: 298 }, { top: 36, right: 36, bottom: 56, left: 36 });
  expect(detail.get("company")).toEqual(base.get("company"));
  expect(detail.size).toBe(13);
  expect([...detail.values()].every(p => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
  expect([...detail.entries()]).not.toEqual([...map.entries()]);
  cy.destroy();
});
