// GraphCanvas 상호작용: 보기 상태(선택·포커스·범례 필터·근거 강조·경로) 적용, 누르기·호버·끌기·배율 LOD, 카메라 이동.
import type { Collection, Core, EdgeSingular, NodeCollection, NodeSingular, SingularElementArgument } from "cytoscape";
import type { GraphPath } from "@/lib/graph-path";
import { ISOLATED_BUNDLE_ID, type EvidenceHighlight, type GraphFocus, type LegendKey } from "@/lib/graph-view";
import { easingVar, lodFor, msVar, type Lod } from "./graph-style";
import { viewportFor, type Viewport } from "./graph-layout";

export interface MotionPrefs {
  reducedMotion: boolean;
  isMobile: boolean;
  /** 데스크톱 상세 패널이 캔버스 오른쪽을 덮는 폭(px). 카메라는 덮이지 않은 영역의 가운데를 쓴다. */
  occludeRight: number;
}

/** 노드를 고르거나 올렸을 때 요약을 보이는 간선 수(최신 사건 순). 나머지는 간선 호버·선택 때 보인다. */
const LABEL_LIMIT = 6;

export interface ViewState {
  selectionId: string | null;
  /** 묶음에 들어간 사건 id. 이 사건을 고르면 묶음 노드를 강조한다. */
  bundled: ReadonlySet<string>;
  focus: GraphFocus | null;
  hidden: ReadonlySet<LegendKey>;
  evidence: EvidenceHighlight | null;
  /** 두 기업 사이 경로(G6). 포커스와 함께 오지 않는다(부모가 보장). */
  path: GraphPath | null;
}

const VIEW_CLASSES = "focused focus-root dimmed emph faded labelled quiet hover focus-hidden filter-hidden path";

/** 경로 요소(노드·선). 경로가 없거나 지금 지도에 없는 요소는 빈 모음. */
export function pathElements(cy: Core, path: GraphPath | null): Collection {
  if (!path) return cy.collection();
  return [...path.nodeIds, ...path.edgeIds].reduce((found, id) => found.union(cy.getElementById(id)), cy.collection());
}

function isShown(ele: SingularElementArgument): boolean {
  if (ele.hasClass("focus-hidden") || ele.hasClass("filter-hidden")) return false;
  if (ele.isEdge()) return isShown(ele.source()) && isShown(ele.target());
  return true;
}

/** 포커스·범례로 숨기지 않은 요소. 클래스로 판단해 같은 동기 구간에서 방금 바꾼 숨김도 반영한다(':visible'은 스타일 갱신 전이면 늦다). */
export function shownElements(cy: Core) {
  return cy.elements().filter((ele) => isShown(ele));
}

/** 묶음에 들어간 사건 id면 묶음 노드로 바꿔 찾는다. */
function elementFor(cy: Core, id: string, bundled: ReadonlySet<string>) {
  return cy.getElementById(bundled.has(id) ? ISOLATED_BUNDLE_ID : id);
}

/** 노드의 보이는 간선 중 요약을 보일 것(최신 사건 순 LABEL_LIMIT개)과 숨길 것. */
function labelEdges(node: NodeSingular) {
  const time = (edge: EdgeSingular) => {
    const other = edge.source().same(node) ? edge.target() : edge.source();
    return (other.data("eventTime") as string | null) ?? (node.data("eventTime") as string | null) ?? "";
  };
  const edges = node.connectedEdges().toArray().filter((e) => isShown(e)) as EdgeSingular[];
  // 최신 사건 먼저(ISO 문자열 비교), 시각 없는 사건은 뒤로. 같은 시각이면 데이터 순서를 지킨다.
  const ranked = edges.map((edge, i) => ({ edge, t: time(edge), i })).sort((a, b) => (a.t === b.t ? a.i - b.i : a.t < b.t ? 1 : -1));
  ranked.forEach(({ edge }, i) => edge.addClass(i < LABEL_LIMIT ? "labelled" : "quiet"));
}

/** 강조: 대상과 이웃은 선명하게, 나머지는 흐리게. 노드면 요약 라벨을 최신 6개로 줄인다. */
function emphasize(cy: Core, target: Collection) {
  const keep = target.nodes().closedNeighborhood().union(target.edges().connectedNodes()).union(target);
  cy.elements().difference(keep).addClass("dimmed");
  keep.addClass("emph");
  target.addClass("focused");
  if (target.length === 1 && target.first().isNode()) {
    labelEdges(target.first() as NodeSingular);
    keep.edges().not(".labelled").addClass("quiet");
  }
}

/**
 * 보기 상태를 캔버스 클래스로 옮긴다(재배치 없음). 우선순위: 숨김(포커스·필터) → 경로 → 근거 강조 → 선택.
 * 경로 모드에서는 경로만 선명하고 나머지는 흐리다. 근거·선택은 그 위에 외곽선만 더한다.
 * 반환값: 카메라가 따라갈 대상(근거 강조 또는 선택, 없으면 빈 모음).
 */
export function applyViewState(cy: Core, state: ViewState): Collection {
  let target: Collection = cy.collection();
  cy.batch(() => {
    cy.elements().removeClass(VIEW_CLASSES);
    if (state.focus) {
      const root = cy.getElementById(state.focus.id);
      if (root.nonempty() && root.isNode()) {
        // 포커스 중심: 스타일은 없고 캡션 정리에서 항상 보이게 하는 표시다(graph-declutter).
        root.addClass("focus-root");
        let nodes: NodeCollection = root as NodeSingular;
        for (let hop = 0; hop < state.focus.hops; hop++) nodes = nodes.closedNeighborhood().nodes();
        cy.elements().difference(nodes.union(nodes.edgesWith(nodes))).addClass("focus-hidden");
      }
    }
    if (state.hidden.size > 0) {
      cy.nodes().forEach((node) => {
        const kind = node.data("kind") === "bundle" ? "issue" : (node.data("kind") as LegendKey);
        if (state.hidden.has(kind)) node.addClass("filter-hidden");
      });
      cy.edges().forEach((edge) => {
        if (state.hidden.has(edge.data("relationType") as LegendKey)) edge.addClass("filter-hidden");
      });
    }
    const route = pathElements(cy, state.path);
    if (route.nonempty()) {
      // 범례로 끈 종류라도 경로 위의 요소는 보여 경로가 끊겨 보이지 않게 한다.
      route.removeClass("filter-hidden");
      cy.elements().difference(route).addClass("dimmed");
      route.addClass("path emph");
      // 양 끝 기업은 고른 두 대상이므로 선택과 같은 외곽선을 준다.
      route.nodes().filter((n) => n.id() === state.path!.from || n.id() === state.path!.to).addClass("focused");
    }
    const mark = (found: Collection) => {
      target = found;
      if (route.empty()) emphasize(cy, found);
      else found.removeClass("dimmed").addClass("focused emph");
    };
    if (state.evidence) {
      const { evidenceId, issueId } = state.evidence;
      const edges = cy.edges().filter((e) => isShown(e) && (e.data("evidenceIds") as string[]).includes(evidenceId));
      const fallback = issueId ? elementFor(cy, issueId, state.bundled).filter((n) => isShown(n)) : cy.collection();
      const found = edges.nonempty() ? edges : fallback;
      if (found.nonempty()) {
        mark(found);
        return;
      }
    }
    if (state.selectionId) {
      const selected = elementFor(cy, state.selectionId, state.bundled);
      if (selected.nonempty() && isShown(selected)) mark(selected);
    }
  });
  return target;
}

/** 선택한 대상으로 카메라를 부드럽게 옮긴다. 모바일은 바텀시트(아래 절반)를 피해 위쪽 가운데에 둔다. */
export function focusCamera(cy: Core, target: Collection, mode: "center" | "neighborhood", prefs: MotionPrefs) {
  if (target.empty() || cy.width() <= 0) return;
  let viewport: Viewport;
  if (mode === "neighborhood") {
    const hood = target.nodes().closedNeighborhood().union(target.edges().connectedNodes()).union(target);
    viewport = viewportFor(cy, hood.boundingBox({ includeLabels: true }), 56, 1.8);
  } else {
    const box = target.nodes().union(target.edges().connectedNodes()).boundingBox({});
    const zoom = Math.min(1.6, Math.max(cy.zoom(), 0.9));
    const cx = box.x1 + box.w / 2;
    const cyy = box.y1 + box.h / 2;
    viewport = { zoom, pan: { x: cy.width() / 2 - cx * zoom, y: cy.height() / 2 - cyy * zoom } };
  }
  if (prefs.isMobile) viewport.pan.y -= cy.height() * 0.22;
  else viewport.pan.x -= prefs.occludeRight / 2;
  moveCamera(cy, viewport, prefs.reducedMotion, "slow");
}

/** 카메라를 옮긴다. 동작 줄이기에서는 즉시. */
export function moveCamera(cy: Core, viewport: Viewport, reducedMotion: boolean, duration: "normal" | "slow") {
  cy.stop(true, false);
  if (reducedMotion) cy.viewport(viewport);
  else cy.animate({ ...viewport, duration: msVar(duration), easing: easingVar("standard") });
}

interface InteractionOptions {
  container: HTMLElement;
  onTap: (target: { kind: "node" | "edge"; id: string } | null) => void;
  /** 강조(선택·근거)가 있으면 호버해도 나머지를 옅게 하지 않는다. */
  hasEmphasis: () => boolean;
  /** 호버가 끝나면 보기 상태를 다시 입힌다. */
  restore: () => void;
  prefs: () => MotionPrefs;
  /** 노드를 끌어 놓으면 위치를 기억한다. */
  onNodeMoved: (id: string, position: { x: number; y: number }) => void;
  lod: { get: () => Lod; set: (lod: Lod) => void };
  onLodChange: (lod: Lod) => void;
  /** 카메라가 멈췄을 때(LOD 갱신 뒤). 캡션 겹침 정리·카메라 기억에 쓴다. */
  onViewportIdle: () => void;
}

/** 이슈–기업 간선(직접 관련·구조적 관련)은 표시만 하고 누르기·선택 대상으로 쓰지 않는다(명세 FS022·D03).
 *  기업 간 간선(사건 공유, FS023)과 사건 간 간선(후속 사건)은 누르면 관계 상세가 열린다. */
export function isDisplayOnlyEdge(relationType: string) {
  return relationType === "INVOLVES" || relationType === "STRUCTURALLY_RELATED_TO";
}

/** 카메라가 이만큼(ms) 움직이지 않으면 멈춘 것으로 보고 LOD·캡션 정리를 한 번 한다.
 *  확대·이동 중에는 스타일을 다시 계산하지 않는다(300노드 측정에서 확대 중 시간의 절반이 스타일 재계산이었다). */
const VIEWPORT_IDLE_MS = 140;

/** 캔버스 이벤트를 붙인다. 반환값은 정리 함수. */
export function bindInteractions(cy: Core, options: InteractionOptions) {
  const { container } = options;
  cy.on("tap", (event) => {
    if (event.target === cy) options.onTap(null);
    else if (event.target.isNode()) options.onTap({ kind: "node", id: event.target.id() });
    else if (!isDisplayOnlyEdge(event.target.data("relationType") as string)) options.onTap({ kind: "edge", id: event.target.id() });
  });
  // 두 번 누르면 그 노드와 이웃이 화면에 꽉 차게 확대한다.
  cy.on("dbltap", "node, edge", (event) => focusCamera(cy, event.target, "neighborhood", options.prefs()));
  // 호버: 이웃을 강조하고 요약을 최신 6개까지 보인다. 강조가 없을 때만 나머지를 옅게.
  cy.on("mouseover", "node", (event) => {
    container.style.setProperty("cursor", "pointer");
    const node = event.target as NodeSingular;
    const hood = node.closedNeighborhood().filter((e) => isShown(e));
    cy.batch(() => {
      hood.addClass("emph");
      node.removeClass("label-cull");
      hood.edges().removeClass("quiet labelled");
      labelEdges(node);
      if (!options.hasEmphasis()) cy.elements().difference(hood).addClass("faded");
    });
  });
  cy.on("mouseout", "node", () => {
    container.style.removeProperty("cursor");
    options.restore();
  });
  // 표시 전용 간선도 호버하면 요약을 보이지만, 누를 수 없으므로 손가락 모양 커서를 쓰지 않는다.
  cy.on("mouseover", "edge", (event) => {
    if (!isDisplayOnlyEdge(event.target.data("relationType") as string)) container.style.setProperty("cursor", "pointer");
    event.target.addClass("emph hover");
  });
  cy.on("mouseout", "edge", () => {
    container.style.removeProperty("cursor");
    options.restore();
  });
  cy.on("free", "node", (event) => {
    const node = event.target as NodeSingular;
    options.onNodeMoved(node.id(), { ...node.position() });
  });
  // 배율 단계(LOD)는 카메라가 멈춘 뒤 한 번만 바꾼다. 움직이는 동안은 직전 화면 텍스처(textureOnViewport)가 쓰인다.
  let timer = 0;
  cy.on("viewport", () => {
    clearTimeout(timer);
    timer = window.setTimeout(() => {
      if (cy.destroyed()) return;
      const next = lodFor(cy.zoom(), cy.edges().length);
      const prev = options.lod.get();
      if (next.scale !== prev.scale || next.nodeLabels !== prev.nodeLabels || next.edgeLabels !== prev.edgeLabels || next.badges !== prev.badges) {
        options.lod.set(next);
        options.onLodChange(next);
      }
      options.onViewportIdle();
    }, VIEWPORT_IDLE_MS);
  });
  return () => clearTimeout(timer);
}
