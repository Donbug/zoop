// 노드 캡션 겹침 정리(R1·R2·R3). 화면에 보이는 캡션을 우선순위 순으로 놓아 보고, 이미 놓인 캡션이나 다른 기업 원과
// 겹치면 숨긴다(.label-cull).
// 우선순위: 선택·경로·포커스 중심(항상 보임) > 강조(선택의 이웃) 기업 > 보유·관심 기업 > 연결 수가 많은 기업 > 묶음 > 사건(연결·근거 순).
// - 재배치·확대 없이 캡션만 숨긴다. 숨긴 노드도 원·배지·연결선은 그대로이고, 확대·호버·선택하면 캡션이 보인다.
// - 카메라가 멈춘 뒤(graph-interaction의 화면 정지)와 보기 상태가 바뀐 뒤에만 계산한다(확대·이동 중에는 하지 않는다).
import type { Core, NodeSingular } from "cytoscape";

type Box = { x1: number; y1: number; x2: number; y2: number };
type Entry = { id: string; box: Box };

/** 캡션 사이 최소 간격(화면 px) */
const GAP = 2;
/** 격자 칸 크기(화면 px) */
const CELL = 96;

function overlaps(a: Box, b: Box) {
  return a.x1 < b.x2 + GAP && b.x1 < a.x2 + GAP && a.y1 < b.y2 + GAP && b.y1 < a.y2 + GAP;
}

/** 균일 격자: 같은 칸의 상자만 비교해 300노드에서도 모든 쌍을 비교하지 않는다. */
class BoxGrid {
  private cells = new Map<string, Entry[]>();
  private keys(box: Box) {
    const keys: string[] = [];
    for (let x = Math.floor(box.x1 / CELL); x <= Math.floor(box.x2 / CELL); x++)
      for (let y = Math.floor(box.y1 / CELL); y <= Math.floor(box.y2 / CELL); y++) keys.push(`${x}:${y}`);
    return keys;
  }
  /** 다른 노드(except가 아닌)의 상자와 겹치는지 */
  hits(box: Box, except: string) {
    return this.keys(box).some((key) => this.cells.get(key)?.some((entry) => entry.id !== except && overlaps(box, entry.box)));
  }
  add(entry: Entry) {
    for (const key of this.keys(entry.box)) {
      const cell = this.cells.get(key);
      if (cell) cell.push(entry);
      else this.cells.set(key, [entry]);
    }
  }
}

/** 낮을수록 먼저 자리를 잡는다. 0은 겹쳐도 숨기지 않는다. */
function rankOf(node: NodeSingular): number {
  if (node.hasClass("focused") || node.hasClass("path") || node.hasClass("focus-root")) return 0;
  const kind = node.data("kind") as string;
  const emphasized = node.hasClass("emph");
  if (kind === "company") return (emphasized ? 1 : 3) + (node.data("mark") ? 0 : 1);
  if (kind === "bundle") return 5;
  return emphasized ? 6 : 7;
}

/** 글자 폭 측정용 캔버스(한 번만 만든다). */
let measureContext: CanvasRenderingContext2D | null = null;
const widthCache = new Map<string, number>();

function textWidth(text: string, font: string) {
  const key = `${font}|${text}`;
  let width = widthCache.get(key);
  if (width === undefined) {
    measureContext ??= document.createElement("canvas").getContext("2d");
    if (!measureContext) return text.length * 8;
    measureContext.font = font;
    width = measureContext.measureText(text).width;
    widthCache.set(key, width);
  }
  return width;
}

/** 노드 아래 캡션의 모델 좌표 상자. Cytoscape의 캡션 위치 캐시는 다음 그리기 전까지 늦을 수 있어
 *  (방금 움직였거나 숨김을 푼 노드) 글꼴·여백 스타일로 직접 계산한다. text-valign: bottom 기준. */
function captionBox(node: NodeSingular, text: string): Box {
  const fontSize = Number.parseFloat(node.style("font-size"));
  const font = `${node.style("font-weight")} ${fontSize}px ${node.style("font-family")}`;
  const lineHeight = Number.parseFloat(node.style("line-height")) || 1.2;
  const padding = Number.parseFloat(node.style("text-background-padding")) || 0;
  const lines = text.split("\n");
  const width = Math.max(...lines.map((line) => textWidth(line, font)));
  const { x, y } = node.position();
  const top = y + node.height() / 2 + Number.parseFloat(node.style("text-margin-y"));
  return { x1: x - width / 2 - padding, x2: x + width / 2 + padding, y1: top - padding, y2: top + lines.length * fontSize * lineHeight + padding };
}

/**
 * 캡션 겹침을 정리하고 숨긴 캡션 수를 돌려준다. 숨김을 먼저 풀어 지금 보기 상태에서 캡션이 보일 노드를 고른 뒤
 * 겹치는 것만 다시 숨긴다(화면이 멈춘 뒤 한 번만 부른다).
 */
export function declutterLabels(cy: Core): number {
  if (cy.destroyed() || cy.width() <= 0) return 0;
  cy.nodes(".label-cull").removeClass("label-cull");
  const zoom = cy.zoom();
  const pan = cy.pan();
  const width = cy.width();
  const height = cy.height();
  const toScreen = (b: Box): Box => ({ x1: b.x1 * zoom + pan.x, y1: b.y1 * zoom + pan.y, x2: b.x2 * zoom + pan.x, y2: b.y2 * zoom + pan.y });
  const onScreen = (b: Box) => b.x2 > 0 && b.x1 < width && b.y2 > 0 && b.y1 < height;

  const candidates: { node: NodeSingular; rank: number; degree: number; label: Box }[] = [];
  // 기업·묶음 원은 모든 캡션의 장애물이다(낮은 우선순위 캡션이 다른 기업 원을 덮지 않게).
  const bodies = new BoxGrid();
  cy.nodes().forEach((node) => {
    if (!node.visible()) return;
    if (node.data("kind") !== "issue") {
      const body = toScreen(node.boundingBox({ includeLabels: false, includeOverlays: false }));
      if (onScreen(body)) bodies.add({ id: node.id(), box: body });
    }
    const caption = node.style("label");
    if (!caption || node.hasClass("dimmed") || node.hasClass("faded")) return;
    const label = toScreen(captionBox(node, caption));
    if (onScreen(label)) candidates.push({ node, rank: rankOf(node), degree: node.degree(false), label });
  });
  candidates.sort(
    (a, b) => a.rank - b.rank || b.degree - a.degree || ((b.node.data("evidenceCount") as number) ?? 0) - ((a.node.data("evidenceCount") as number) ?? 0),
  );

  const placed = new BoxGrid();
  const culled: NodeSingular[] = [];
  for (const { node, rank, label } of candidates) {
    const id = node.id();
    if (rank > 0 && (placed.hits(label, id) || bodies.hits(label, id))) culled.push(node);
    else placed.add({ id, box: label });
  }
  if (culled.length > 0) cy.batch(() => culled.forEach((node) => node.addClass("label-cull")));
  return culled.length;
}
