// GraphCanvas 배치: fcose(force-directed) 또는 dagre(흐름 순) 배치, 시작 위치, 화면 맞춤, 퍼짐 애니메이션.
// 모드를 바꿔도 남는 노드는 제자리에서 시작해 새 노드만 퍼져 나온다. 동작 줄이기에서는 즉시 배치한다.
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
import dagre from "cytoscape-dagre";
import fcose from "cytoscape-fcose";
import { bundleSizeAt, easingVar, msVar } from "./graph-style";

cytoscape.use(dagre);
cytoscape.use(fcose);

export type LayoutName = "fcose" | "dagre";
export type Positions = Map<string, { x: number; y: number }>;
export type Viewport = { zoom: number; pan: { x: number; y: number } };
/** 화면 가장자리 여백(px) */
export type Insets = { top: number; right: number; bottom: number; left: number };

/** 화면 맞춤 여백: 아래(데스크톱)·오른쪽(모바일) 조작 도구(44px + 12px 간격)에 라벨이 가리지 않게 한다. */
export const FIT_PADDING = 68;

/** 경계 상자에 맞는 배율·위치. 작은 지도를 과하게 확대하지 않는다(최대 1.4). */
export function viewportFor(cy: Core, bounds: { x1: number; y1: number; w: number; h: number }, padding: number, maxZoom = 1.4): Viewport {
  const zoom = Math.max(
    cy.minZoom(),
    Math.min(maxZoom, (cy.width() - padding * 2) / Math.max(bounds.w, 1), (cy.height() - padding * 2) / Math.max(bounds.h, 1)),
  );
  return { zoom, pan: { x: cy.width() / 2 - (bounds.x1 + bounds.w / 2) * zoom, y: cy.height() / 2 - (bounds.y1 + bounds.h / 2) * zoom } };
}

/** 배율이 이보다 낮으면 사건 캡션(0.55)·간선 요약(0.95)이 숨으므로 맞출 때 그 라벨 폭을 비워 두지 않는다(graph-style LOD와 같은 값). */
const LABEL_TIERS = [
  { minZoom: 0.95, labelled: (eles: cytoscape.Collection) => eles },
  { minZoom: 0.55, labelled: (eles: cytoscape.Collection) => eles.nodes() },
  { minZoom: 0, labelled: (eles: cytoscape.Collection) => eles.nodes('[kind != "issue"]') },
];

/**
 * 요소 모음을 화면에 맞춘다. 라벨은 화면 글자 크기(13px)를 지키려고 배율 1 미만에서 배율에 반비례해 커지므로,
 * 라벨이 노드 경계 밖으로 나가는 폭을 '화면 픽셀'로 재서 목표 배율에서도 같은 폭을 비워 둔다.
 * 목표 배율에서 숨는 라벨(사건 캡션·간선 요약)은 빼고 잰다.
 * (라벨 포함 경계로 바로 맞추면 축소된 화면의 큰 라벨 때문에 작은 지도가 과하게 작아진다.)
 */
/** 화면에서 가장 큰 노드(기업·묶음)의 반지름(px) */
const NODE_HALF_PX = 36;

/** 노드 중심점들의 경계 상자 */
function centersBox(eles: cytoscape.Collection) {
  const xs = eles.nodes().map((n) => n.position("x"));
  const ys = eles.nodes().map((n) => n.position("y"));
  const [x1, x2, y1, y2] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  return { x1, x2, y1, y2, w: x2 - x1, h: y2 - y1 };
}

export function fitViewport(
  cy: Core,
  eles: cytoscape.Collection,
  padding: number | Insets,
  maxZoom = 1.4,
  labelOverhang?: Insets,
  /** 맞출 요소 밖에 따로 비워 둘 화면 자리(px), 예: 가장자리 묶음 */
  reserve: Insets = { top: 0, right: 0, bottom: 0, left: 0 },
): Viewport {
  const pad = typeof padding === "number" ? { top: padding, right: padding, bottom: padding, left: padding } : padding;
  // 노드 크기도 배율에 따라 모델 크기가 바뀌므로(기업·묶음은 화면 최소 크기) 중심점 경계로 재고,
  // 노드 반지름과 라벨은 화면 픽셀 여백으로 더한다.
  const nodes = centersBox(eles);
  const toScreen = Math.min(1, cy.zoom());
  const availW = cy.width() - pad.left - pad.right;
  const availH = cy.height() - pad.top - pad.bottom;
  // 배율 z(≤1)에서 화면 폭 = 노드 폭·z + 라벨 폭. z>1이면 라벨도 배율만큼 커진다.
  const fitAxis = (size: number, avail: number, extra: number) => {
    const below = (avail - extra) / Math.max(size, 1);
    return below <= 1 ? below : avail / Math.max(size + extra, 1);
  };
  let result: Viewport = { zoom: 1, pan: { x: 0, y: 0 } };
  for (const tier of LABEL_TIERS) {
    const all = tier.labelled(eles).boundingBox({ includeLabels: true });
    // 지금 배율에서 노드·라벨이 중심점 경계 밖으로 넘치는 폭(화면 px, 배율 1 이하 기준, 최소 노드 반지름).
    // 호출부가 알면 그 값을 쓴다.
    const measured = labelOverhang
      ? { l: labelOverhang.left, r: labelOverhang.right, t: labelOverhang.top, b: labelOverhang.bottom }
      : {
          l: Math.max(NODE_HALF_PX, (nodes.x1 - all.x1) * toScreen),
          r: Math.max(NODE_HALF_PX, (all.x2 - nodes.x2) * toScreen),
          t: Math.max(NODE_HALF_PX, (nodes.y1 - all.y1) * toScreen),
          b: Math.max(NODE_HALF_PX, (all.y2 - nodes.y2) * toScreen),
        };
    const over = { l: measured.l + reserve.left, r: measured.r + reserve.right, t: measured.t + reserve.top, b: measured.b + reserve.bottom };
    const zoom = Math.max(cy.minZoom(), Math.min(maxZoom, fitAxis(nodes.w, availW, over.l + over.r), fitAxis(nodes.h, availH, over.t + over.b)));
    const grow = Math.max(1, zoom);
    const left = nodes.x1 * zoom - over.l * grow;
    const right = nodes.x2 * zoom + over.r * grow;
    const top = nodes.y1 * zoom - over.t * grow;
    const bottom = nodes.y2 * zoom + over.b * grow;
    // 여백이 비대칭이면 남은 영역의 가운데에 둔다.
    const cx = pad.left + availW / 2;
    const cyy = pad.top + availH / 2;
    result = { zoom, pan: { x: cx - (left + right) / 2, y: cyy - (top + bottom) / 2 } };
    if (labelOverhang || zoom >= tier.minZoom) break;
  }
  return result;
}

/** 포커스 방사형 배치의 목표 배율: 사건 캡션(0.55)과 근거 배지(0.8)가 보이는 배율 */
const FOCUS_ZOOM = 0.9;
/**
 * 포커스 배치에서 노드 중심 밖으로 필요한 자리(화면 px). 노드 크기는 배율에 따라 모델 크기가 바뀌므로(기업은 화면 최소 44px)
 * 중심점 기준으로 잰다: 좌우는 두 줄 캡션(최대 약 170px)의 절반, 위는 노드 반지름 + 배지, 아래는 노드 반지름 + 캡션.
 */
export const FOCUS_LABEL_OVERHANG: Insets = { top: 44, right: 88, bottom: 80, left: 88 };
/** 링이 촘촘하면 노드를 안팎으로 번갈아(최대 4겹) 놓는다. 겹 사이 거리는 가장 큰 노드의 몫과 같다. */
const MAX_STAGGER = 4;
/** 링 사이 최소 간격, 중심과 첫 링 사이 최소 반지름(모델 좌표) */
const RING_GAP = 140;
const MIN_INNER_RADIUS = 100;

/** 타원 둘레(라마누잔 근사) */
function ellipsePerimeter(rx: number, ry: number) {
  return Math.PI * (3 * (rx + ry) - Math.sqrt((3 * rx + ry) * (rx + 3 * ry)));
}

/**
 * 타원 둘레 위의 점들(매개변수 t). fractions는 둘레에 대한 호 길이 비율(0~1)이고, 비율 0은 극각 startAngle 방향이다
 * (원래 배치의 방향을 유지). 매개변수 t와 호 길이의 대응표를 만들어 보간한다.
 */
function ellipsePoints(rx: number, ry: number, fractions: number[], startAngle: number) {
  const steps = 720;
  const lengths = [0];
  for (let i = 1; i <= steps; i++) {
    const [a, b] = [((i - 1) / steps) * Math.PI * 2, (i / steps) * Math.PI * 2];
    lengths.push(lengths[i - 1]! + Math.hypot(rx * (Math.cos(b) - Math.cos(a)), ry * (Math.sin(b) - Math.sin(a))));
  }
  const total = lengths[steps]!;
  const tAt = (s: number) => {
    const target = ((s % total) + total) % total;
    let i = lengths.findIndex((l) => l >= target);
    if (i <= 0) i = 1;
    const f = (target - lengths[i - 1]!) / Math.max(lengths[i]! - lengths[i - 1]!, 1e-9);
    return ((i - 1 + f) / steps) * Math.PI * 2;
  };
  // 극각 θ 방향의 점의 매개변수: tan θ = ry·sin t / (rx·cos t)
  const t0 = (Math.atan2(rx * Math.sin(startAngle), ry * Math.cos(startAngle)) + Math.PI * 2) % (Math.PI * 2);
  const s0 = (t0 / (Math.PI * 2)) * steps;
  const startLength = lengths[Math.floor(s0)]! + (s0 % 1) * (lengths[Math.min(steps, Math.floor(s0) + 1)]! - lengths[Math.floor(s0)]!);
  return fractions.map((f) => tAt(startLength + f * total));
}

/**
 * 포커스 방사형 배치(G2): 포커스 노드를 원래 자리에 두고 1단계 이웃은 첫 링, 2단계 이웃은 둘째 링(타원)에 놓는다.
 * 링의 크기는 목표 배율(0.9)에서 화면 영역(area, px)을 채우도록 정하고, 촘촘하면 안팎으로 번갈아 놓거나 링을 키운다.
 * 각 링 안의 순서는 원래 배치에서 중심을 기준으로 본 방향 순서라 전체 지도의 방향 감각이 유지된다.
 * 범례로 숨긴 노드도 자리를 받는다(필터는 재배치하지 않는다).
 */
export function focusPositions(cy: Core, focus: { id: string; hops: number }, base: Positions, area: { width: number; height: number }, labelOverhang: Insets = FOCUS_LABEL_OVERHANG): Positions {
  const result: Positions = new Map();
  const root = cy.getElementById(focus.id);
  const center = base.get(focus.id);
  if (root.empty() || !root.isNode() || !center) return result;
  result.set(focus.id, center);
  const ring1 = root.neighborhood().nodes();
  const ring2 = focus.hops >= 2 ? ring1.neighborhood().nodes().difference(ring1).difference(root) : cy.collection();
  const rings = [ring1, ring2].filter((ring) => ring.nonempty());
  if (rings.length === 0) return result;

  // 화면 영역 비율로 타원 모양을 정한다. 좁은 화면(모바일)에서는 세로로 긴 타원이 되어 좌우 캡션 열이 서로 겹치지 않는다.
  const innerW = area.width - labelOverhang.left - labelOverhang.right;
  const innerH = area.height - labelOverhang.top - labelOverhang.bottom;
  const aspect = Math.max(innerH, 1) / Math.max(innerW, 1);
  const angleOf = (node: NodeSingular) => {
    const p = base.get(node.id()) ?? node.position();
    return Math.atan2(p.y - center.y, p.x - center.x);
  };
  const sortedRings = rings.map((ring) =>
    (ring.toArray() as NodeSingular[]).map((node) => ({ node, angle: angleOf(node) })).sort((a, b) => a.angle - b.angle),
  );
  /** 배율 zoom에서 노드 모델 크기(기업은 화면 최소 44px라 배율이 낮으면 커진다. 모바일 크기로 넉넉히 잡는다) */
  const sizeAt = (node: NodeSingular, zoom: number) => (node.data("kind") === "company" ? Math.max(72, 44 / zoom) : 36);
  // 노드마다 둘레 몫: 대각선으로 이웃해도 경계 상자가 겹치지 않도록 크기의 √2배 + 여백
  const shareAt = (node: NodeSingular, zoom: number) => sizeAt(node, zoom) * Math.SQRT2 + 12;
  /**
   * 링 하나: 바깥 끝이 maxExtent를 넘지 않게 노드 몫의 합을 둘레에 담는다. 모자라면 안팎으로 번갈아(겹) 놓아
   * 한 겹의 몫을 줄이되 겹이 늘어난 만큼 기준 반지름을 줄인다. 안 되면 ok=false(더 낮은 배율에서 다시 시도).
   */
  const ringAt = (shares: number[], maxExtent: number, minRx: number, gap: number) => {
    const demand = shares.reduce((sum, s) => sum + s, 0);
    for (let layers = 1; layers <= Math.min(MAX_STAGGER, shares.length); layers++) {
      const rx = maxExtent - (layers - 1) * gap;
      if (rx < minRx) break;
      if (ellipsePerimeter(rx, rx * aspect) * layers >= demand) return { rx, layers, ok: true };
    }
    return { rx: maxExtent, layers: 1, ok: false };
  };
  // 목표 배율(0.9)부터 낮춰 가며 링이 화면 영역에 들어가는 첫 배율을 고른다.
  let plan: { rx: number; layers: number }[] = [];
  let zoomUsed = FOCUS_ZOOM;
  let gap = RING_GAP;
  for (const zoom of [FOCUS_ZOOM, 0.8, 0.7, 0.6, 0.5, 0.42, 0.35, 0.3, 0.25, 0.2, 0.15]) {
    zoomUsed = zoom;
    const shares = sortedRings.map((ring) => ring.map(({ node }) => shareAt(node, zoom)));
    const largest = Math.max(...shares.flat());
    gap = largest; // 겹 사이·링 사이 거리
    const availRx = Math.max(MIN_INNER_RADIUS, innerW / zoom / 2);
    // 중심 노드와 첫 링이 겹치지 않는 최소 반지름
    const minRx = Math.max(MIN_INNER_RADIUS, (sizeAt(root as NodeSingular, zoom) / 2) * Math.SQRT2 + largest / 2);
    let ok: boolean;
    if (sortedRings.length === 2) {
      const inner = ringAt(shares[0]!, Math.max(minRx, availRx * 0.4), minRx, gap);
      const innerExtent = inner.rx + (inner.layers - 1) * gap;
      const outer = ringAt(shares[1]!, availRx, innerExtent + Math.max(RING_GAP, gap), gap);
      plan = [inner, outer];
      ok = inner.ok && outer.ok;
    } else {
      const only = ringAt(shares[0]!, Math.max(minRx, availRx), minRx, gap);
      plan = [only];
      ok = only.ok;
    }
    if (ok) break;
  }
  sortedRings.forEach((sorted, index) => {
    const { rx, layers } = plan[index]!;
    const ry = rx * aspect;
    // 이웃한 두 노드 사이 호 길이 = 두 몫의 평균 / 겹 수. 남는 둘레는 고르게 나눠 준다.
    const shares = sorted.map(({ node }) => shareAt(node, zoomUsed) / layers);
    const needs = shares.map((s, k) => (s + shares[(k + 1) % shares.length]!) / 2);
    const slack = Math.max(0, ellipsePerimeter(rx, ry) - needs.reduce((sum, s) => sum + s, 0)) / needs.length;
    const steps = needs.map((need) => need + slack);
    const total = steps.reduce((sum, s) => sum + s, 0);
    const fractions = steps.map((_, k) => steps.slice(0, k).reduce((sum, s) => sum + s, 0) / total);
    const params = ellipsePoints(rx, ry, fractions, sorted[0]!.angle);
    sorted.forEach(({ node }, k) => {
      const layer = k % layers;
      const [lx, ly] = [rx + layer * gap, ry + layer * gap * Math.max(1, aspect)];
      result.set(node.id(), { x: center.x + lx * Math.cos(params[k]!), y: center.y + ly * Math.sin(params[k]!) });
    });
  });
  return result;
}

export interface Placement {
  /** 애니메이션 시작 위치(기억한 노드는 제자리, 새 노드는 이웃 곁) */
  start: Positions;
  final: Positions;
  /** 이전 배치에서 기억한 노드가 하나도 없으면 첫 표시 */
  firstShow: boolean;
}

/** 가장자리에 둘 노드(연결 없는 사건 묶음)와 나머지 노드 경계 사이 화면 간격(px). 아래쪽 노드 캡션 자리를 포함한다. */
const EDGE_GAP_PX = 48;

/**
 * 가장자리 노드(연결 없는 사건 묶음)를 나머지 노드의 가장자리에 둔다: 지도가 화면 비율보다 납작하면 아래 가운데,
 * 아니면 오른쪽 가운데(남는 쪽에 둬 화면 맞춤 배율을 덜 줄인다). 묶음은 배율이 낮을수록 모델 크기가 커지므로(화면 최소 48px)
 * 맞출 배율(zoom)에서의 크기와 간격으로 자리를 잡는다.
 */
export function placeEdgeNode(cy: Core, edgeNode: cytoscape.CollectionReturnValue, isMobile: boolean, zoom: number) {
  const others = cy.nodes().difference(edgeNode);
  const b = others.nonempty() ? centersBox(others) : { x1: 0, x2: 0, y1: 0, y2: 0, w: 0, h: 0 };
  // 다른 노드 중심에서 (가장 큰 노드 반지름 + 간격)만큼 떨어진 곳에 묶음 가장자리가 오게 한다.
  const offset = (NODE_HALF_PX + EDGE_GAP_PX) / Math.min(1, zoom) + bundleSizeAt(zoom, isMobile) / 2;
  const position = edgeSide(cy, others) === "bottom" ? { x: b.x1 + b.w / 2, y: b.y2 + offset } : { x: b.x2 + offset, y: b.y1 + b.h / 2 };
  edgeNode.position(position);
  return position;
}

/** 묶음을 둘 쪽: 지도가 화면 비율보다 납작하면 아래에 남는 자리가 있으므로 아래, 아니면 오른쪽 */
export function edgeSide(cy: Core, others: cytoscape.Collection): "bottom" | "right" {
  const b = others.nonempty() ? centersBox(others) : { w: 1, h: 1 };
  return b.h / Math.max(b.w, 1) < cy.height() / Math.max(cy.width(), 1) ? "bottom" : "right";
}

/** 묶음이 화면에서 차지하는 자리(px): 간격 + 지름 48 + 캡션. 맞출 때 그쪽 여백에 더한다. */
export function edgeNodeFootprint(side: "bottom" | "right"): Insets {
  return side === "bottom" ? { top: 0, right: 0, bottom: EDGE_GAP_PX + 48 + 28, left: 0 } : { top: 0, right: EDGE_GAP_PX + 48 + 64, bottom: 0, left: 0 };
}

/** fcose 난수 씨앗(R4). 같은 데이터·같은 화면 종류면 새로고침해도 같은 배치가 나온다. */
const LAYOUT_SEED = 0x5eed;

/** 작은 결정적 난수 생성기(mulberry32). fcose가 쓰는 Math.random을 배치 동안만 바꿔 끼운다. */
function seededRandom(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * 배치를 계산해 노드를 최종 위치에 둔다(동기). 애니메이션은 revealPlacement가 맡는다.
 * edgeNodeId가 있으면 그 노드는 배치에서 빼고 나머지의 가장자리(가로로 긴 화면은 오른쪽 가운데, 세로로 긴 화면은 아래 가운데)에 둔다.
 * exact면(같은 데이터로 지도에 돌아옴) 기억한 좌표를 그대로 쓰고 배치를 다시 계산하지 않는다(R4·FS044).
 */
export function placeNodes(cy: Core, layoutName: LayoutName, isMobile: boolean, remembered: Positions, edgeNodeId?: string, exact = false): Placement {
  if (exact && cy.nodes().toArray().every((n) => remembered.has(n.id()))) {
    const final: Positions = new Map(cy.nodes().map((n) => [n.id(), remembered.get(n.id())!] as const));
    cy.nodes().positions((n) => final.get(n.id())!);
    return { start: final, final, firstShow: true };
  }
  const known = cy.nodes().filter((n) => remembered.has(n.id()));
  const incremental = layoutName === "fcose" && known.length > 0 && known.length >= cy.nodes().length / 2;
  // 시작 위치: 기억한 노드는 제자리, 새 노드는 이미 놓인 이웃 곁(없으면 가운데)에서 출발한다.
  const center = known.length > 0 ? (() => {
    const b = known.boundingBox({});
    return { x: b.x1 + b.w / 2, y: b.y1 + b.h / 2 };
  })() : { x: 0, y: 0 };
  const start: Positions = new Map();
  cy.nodes().forEach((node, i) => {
    const saved = remembered.get(node.id());
    if (saved) return void start.set(node.id(), saved);
    const anchor = node.neighborhood("node").filter((n) => remembered.has(n.id())).first();
    const base = anchor.nonempty() ? remembered.get(anchor.id())! : center;
    const angle = i * 2.399; // 황금각으로 흩어 겹침을 피한다
    start.set(node.id(), { x: base.x + Math.cos(angle) * 24, y: base.y + Math.sin(angle) * 24 });
  });
  cy.nodes().positions((node) => start.get(node.id())!);

  const edgeNode = edgeNodeId ? cy.getElementById(edgeNodeId) : cy.collection();
  const laid = cy.elements().difference(edgeNode);
  const layout =
    layoutName === "dagre"
      ? laid.layout({ name: "dagre", rankDir: "LR", nodeSep: 48, rankSep: 140, animate: false, fit: false } as cytoscape.LayoutOptions)
      : laid.layout({
          name: "fcose",
          quality: incremental ? "proof" : "default",
          randomize: !incremental,
          animate: false,
          fit: false,
          nodeDimensionsIncludeLabels: true,
          packComponents: true,
          // 허브 주위 요약과 두 줄 캡션이 서로 겹치지 않도록 관계 길이·반발력을 확보한다.
          nodeRepulsion: (node: NodeSingular) => node.data("kind") === "company" ? 80000 : 14000,
          idealEdgeLength: (edge: cytoscape.EdgeSingular) => edge.data("relationType") === "SHARES_ISSUE" ? 360 : (isMobile ? 170 : 210),
          nodeSeparation: 110,
          tile: true,
          tilingPaddingHorizontal: 140,
          tilingPaddingVertical: 64,
        } as cytoscape.LayoutOptions);
  if (laid.nodes().nonempty()) {
    const random = Math.random;
    Math.random = seededRandom(LAYOUT_SEED);
    // fcose는 기업 원을 전체 보기에서의 크기(.layout-size)로 보고 배치한다(R2). 흐름 순 배치는 층 간격이 따로 있다.
    const sized = layoutName === "fcose" ? laid.nodes('[kind = "company"]').addClass("layout-size") : cy.collection();
    try {
      layout.run();
    } finally {
      Math.random = random;
      sized.removeClass("layout-size");
    }
  }
  if (edgeNode.nonempty()) placeEdgeNode(cy, edgeNode, isMobile, cy.zoom());

  const final: Positions = new Map();
  cy.nodes().forEach((node) => void final.set(node.id(), { ...node.position() }));
  const firstShow = known.empty();
  if (firstShow) {
    const bounds = cy.elements().boundingBox({ includeLabels: true });
    // 첫 표시: 최종 배치의 가운데에서 모든 노드가 퍼져 나온다(카메라는 최종 화면에 먼저 맞춘다).
    const mid = { x: bounds.x1 + bounds.w / 2, y: bounds.y1 + bounds.h / 2 };
    cy.nodes().forEach((node, i) => void start.set(node.id(), { x: mid.x + Math.cos(i * 2.399) * 12, y: mid.y + Math.sin(i * 2.399) * 12 }));
  }
  return { start, final, firstShow };
}

/**
 * 배치 애니메이션: 시작 위치로 되돌린 뒤 최종 위치로 퍼진다. 새 노드는 투명에서 나타난다.
 * 애니메이션이 끝날 무렵 onSettled를 부른다. 반환값은 취소 함수.
 */
export function revealPlacement(cy: Core, placement: Placement, target: Viewport, remembered: Positions, onSettled: () => void) {
  const { start, final, firstShow } = placement;
  const duration = msVar("graph-layout");
  const easing = easingVar("enter-expressive");
  let timer = 0;
  cy.batch(() => {
    cy.nodes().positions((node) => start.get(node.id())!);
    cy.nodes().filter((n) => !remembered.has(n.id())).addClass("entering");
  });
  if (firstShow) cy.viewport(target);
  const frame = requestAnimationFrame(() => {
    if (cy.destroyed()) return;
    cy.nodes().removeClass("entering");
    cy.nodes().forEach((node) => {
      node.animate({ position: final.get(node.id())! }, { duration, easing });
    });
    if (!firstShow) cy.animate({ ...target, duration, easing });
    timer = window.setTimeout(() => !cy.destroyed() && onSettled(), duration);
  });
  return () => {
    cancelAnimationFrame(frame);
    clearTimeout(timer);
  };
}
