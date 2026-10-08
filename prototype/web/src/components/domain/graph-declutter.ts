// 카메라 정지·선택·호버 뒤에만 실제로 그려지는 이름과 관계 요약을 화면 좌표로 정리한다.
// 노드·연결·데이터는 남기고 선택 대상과 포커스 중심을 우선해 겹치는 낮은 순위 라벨만 숨긴다.
import type { Core, SingularElementArgument } from "cytoscape";

export type LabelBox = { x1: number; y1: number; x2: number; y2: number };
type Entry = { id: string; box: LabelBox };
export interface LabelCandidate extends Entry {
  priority: number;
  distance: number;
  degree: number;
  evidenceCount: number;
}

/** 화면 최소 간격. 배율에 따라 바뀌지 않는다. */
const GAP = 2;
const CELL = 96;

function overlaps(a: LabelBox, b: LabelBox) {
  return a.x1 < b.x2 + GAP && b.x1 < a.x2 + GAP && a.y1 < b.y2 + GAP && b.y1 < a.y2 + GAP;
}

/** 가까운 칸만 비교한다. 간격만큼 검색 범위도 넓혀 칸 경계의 충돌을 놓치지 않는다. */
class BoxGrid {
  private cells = new Map<string, Entry[]>();
  private keys(box: LabelBox, gap = 0) {
    const keys: string[] = [];
    for (let x = Math.floor((box.x1 - gap) / CELL); x <= Math.floor((box.x2 + gap) / CELL); x++)
      for (let y = Math.floor((box.y1 - gap) / CELL); y <= Math.floor((box.y2 + gap) / CELL); y++) keys.push(`${x}:${y}`);
    return keys;
  }
  hits(box: LabelBox, except: string) {
    return this.keys(box, GAP).some((key) => this.cells.get(key)?.some((entry) => entry.id !== except && overlaps(box, entry.box)));
  }
  add(entry: Entry) {
    for (const key of this.keys(entry.box)) {
      const cell = this.cells.get(key);
      if (cell) cell.push(entry);
      else this.cells.set(key, [entry]);
    }
  }
}

/** 렌더러와 독립적인 결정적 선별. priority 0은 선택·호버·포커스 중심이므로 남긴다. */
export function culledLabelIds(candidates: readonly LabelCandidate[], obstacles: readonly Entry[]): Set<string> {
  const bodies = new BoxGrid();
  obstacles.forEach((entry) => bodies.add(entry));
  const placed = new BoxGrid();
  const culled = new Set<string>();
  const ranked = [...candidates].sort((a, b) =>
    a.priority - b.priority || a.distance - b.distance || b.degree - a.degree || b.evidenceCount - a.evidenceCount ||
    (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
  );
  for (const entry of ranked) {
    if (entry.priority > 0 && (placed.hits(entry.box, entry.id) || bodies.hits(entry.box, entry.id))) culled.add(entry.id);
    else placed.add(entry);
  }
  return culled;
}

function rankOf(element: SingularElementArgument): number {
  if (element.hasClass("focused") || element.hasClass("hover") || element.hasClass("focus-root")) return 0;
  if (element.isEdge()) return 7;
  if (element.data("kind") === "company") return element.hasClass("emph") || element.hasClass("path") ? 1 : element.data("mark") ? 2 : 3;
  if (element.data("kind") === "bundle") return 4;
  return element.hasClass("emph") || element.hasClass("path") ? 5 : 6;
}

/**
 * Cytoscape 라벨 전용 bounds에는 실제 줄바꿈·굵기·배경 여백·회전이 포함된다.
 * 숨김 클래스를 풀고 한 번만 렌더 좌표를 갱신한 뒤 캐시된 bounds를 사용한다.
 * 카메라·노드 위치는 변경하지 않아 선별 전후 화면 면적도 바뀌지 않는다.
 */
export function declutterLabels(cy: Core): number {
  if (cy.destroyed() || cy.width() <= 0 || cy.height() <= 0) return 0;
  cy.elements(".label-cull").removeClass("label-cull");
  // 런타임의 공개 useCache 옵션이 현재 Cytoscape 타입 정의에는 빠져 있다.
  const refreshBounds = { useCache: false, includeOverlays: false };
  cy.elements().boundingBox(refreshBounds);
  const zoom = cy.zoom();
  const pan = cy.pan();
  const width = cy.width();
  const height = cy.height();
  const toScreen = (b: LabelBox): LabelBox => ({ x1: b.x1 * zoom + pan.x, y1: b.y1 * zoom + pan.y, x2: b.x2 * zoom + pan.x, y2: b.y2 * zoom + pan.y });
  const onScreen = (b: LabelBox) => b.x2 > 0 && b.x1 < width && b.y2 > 0 && b.y1 < height;
  const anchors = cy.nodes(".focused, .hover, .focus-root").map((node) => node.renderedPosition());
  const candidates: LabelCandidate[] = [];
  const bodies: Entry[] = [];
  cy.elements().forEach((element) => {
    if (!element.visible()) return;
    if (element.isNode() && element.data("kind") !== "issue") {
      const body = toScreen(element.boundingBox({ includeLabels: false, includeOverlays: false }));
      if (onScreen(body)) bodies.push({ id: element.id(), box: body });
    }
    if (!element.style("label") || element.hasClass("dimmed") || element.hasClass("faded")) return;
    const bounds = element.boundingBox({
      includeNodes: false, includeEdges: false, includeLabels: true, includeOverlays: false, includeUnderlays: false,
    });
    if (bounds.w <= 0 || bounds.h <= 0) return;
    const box = toScreen(bounds);
    if (!onScreen(box)) return;
    const x = (box.x1 + box.x2) / 2;
    const y = (box.y1 + box.y2) / 2;
    const distance = element.isNode() && element.data("kind") === "issue" && anchors.length
      ? Math.min(...anchors.map((at) => (x - at.x) ** 2 + (y - at.y) ** 2)) : 0;
    candidates.push({
      id: element.id(), box, priority: rankOf(element), distance,
      degree: element.isNode() ? element.degree(false) : 0,
      evidenceCount: (element.data("evidenceCount") as number | undefined) ?? 0,
    });
  });
  const culled = culledLabelIds(candidates, bodies);
  if (culled.size) cy.batch(() => culled.forEach((id) => cy.getElementById(id).addClass("label-cull")));
  return culled.size;
}
