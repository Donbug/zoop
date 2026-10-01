// GraphCanvas: Cytoscape.js로 기업·사건 관계를 GraphDB 시각화(Neo4j Browser/Bloom) 관례대로 그린다(design-direction §4).
// 이 파일은 React 수명주기·도구 막대만 맡는다. 스타일·LOD는 graph-style, 요소 정의는 graph-elements,
// 배치·퍼짐 애니메이션은 graph-layout, 선택·호버·카메라는 graph-interaction에 있다.
// - force-directed(fcose) 배치, 노드 끌기, 호버하면 이웃 강조, 누르면 선택(카메라가 부드럽게 따라감), 두 번 누르면 이웃으로 확대.
// - 포커스: 남은 노드를 방사형 자리로 옮기고(전체 배치 위치는 positionsRef에 그대로), 나오면 그 위치로 되돌린다.
// - 경로(G6): 경로만 선명하게 두고 경로에 맞춰 카메라를 옮긴다(재배치 없음).
// - 미니맵(G7): 데스크톱에서 보이는 노드가 60개를 넘을 때만 오른쪽 아래(graph-minimap).
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
import { GitBranch, Maximize2, Minus, MoreHorizontal, Network, Plus } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Popover } from "@/components/ui/popover";
import { Tooltip } from "@/components/ui/tooltip";
import { companyGlyph, glyphColor } from "@/lib/graph-visuals";
import { useMediaQuery, useTheme } from "@/lib/theme";
import type { GraphPath } from "@/lib/graph-path";
import { ISOLATED_BUNDLE_ID, isolatedBundleLabel, type EvidenceHighlight, type GraphFocus, type LegendKey } from "@/lib/graph-view";
import { cn } from "@/lib/utils";
import { toElements } from "./graph-elements";
import { applyViewState, bindInteractions, focusCamera, moveCamera, pathElements, shownElements, type ViewState } from "./graph-interaction";
import {
  FIT_PADDING,
  FOCUS_LABEL_OVERHANG,
  edgeNodeFootprint,
  edgeSide,
  fitViewport,
  focusPositions,
  placeEdgeNode,
  placeNodes,
  revealPlacement,
  type Insets,
  type LayoutName,
  type Positions,
} from "./graph-layout";
import { MINIMAP_MIN_NODES, attachMinimap } from "./graph-minimap";
import { buildStyle, easingVar, lodFor, msVar, type Lod } from "./graph-style";

export type GraphSelection = { kind: "node" | "edge"; id: string };
/** 이 노드를 화면 가운데로 확대해 옮겨 달라는 요청. 같은 노드를 다시 요청해도 seq가 바뀌면 다시 옮긴다. */
export type CenterRequest = { id: string; seq: number };

/** 사이드바에서 고른 기업으로 옮길 때의 최소 배율(기업 원이 화면에서 약 85px). */
const CENTER_ZOOM = 1.3;

interface GraphCanvasProps {
  nodes: Schemas["GraphNode"][];
  edges: Schemas["GraphEdge"][];
  selection: GraphSelection | null;
  onSelect: (selection: GraphSelection | null) => void;
  /** 스크린리더용 요약 (예: "시장 전체 지도. 기업 1개, 사건 3개") */
  ariaLabel: string;
  className?: string;
  /** 작은 데모(디자인시스템)에서는 도구 막대를 줄인다. */
  minimalToolbar?: boolean;
  /** 연결 없는 사건을 묶음 노드 하나로 모은다(G1). 묶음 id는 ISOLATED_BUNDLE_ID. */
  groupIsolated?: boolean;
  /** 이 노드의 n단계 이웃만 남긴다(G2). */
  focus?: GraphFocus | null;
  /** 범례에서 끈 노드 종류·관계 유형(G5). 표시만 바꾸고 재배치하지 않는다. */
  hidden?: ReadonlySet<LegendKey>;
  /** 근거 창에서 `지도에서 보기`를 누른 인용(G4). */
  evidence?: EvidenceHighlight | null;
  /** 두 기업 사이 경로(G6). 경로 요소만 선명하게 두고 카메라를 경로에 맞춘다. focus와 함께 주지 않는다. */
  path?: GraphPath | null;
  /** 사이드바 기업 선택: 그 노드를 가운데로 확대·이동한다(동작 줄이기면 즉시). */
  centerOn?: CenterRequest | null;
}

const NO_HIDDEN: ReadonlySet<LegendKey> = new Set();

export function GraphCanvas({
  nodes,
  edges,
  selection,
  onSelect,
  ariaLabel,
  className,
  minimalToolbar,
  groupIsolated = false,
  focus = null,
  hidden = NO_HIDDEN,
  evidence = null,
  path = null,
  centerOn = null,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bundleButtonRef = useRef<HTMLButtonElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const { theme } = useTheme();
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const isMobile = useMediaQuery("(max-width: 768px)");
  const [layoutName, setLayoutName] = useState<LayoutName>("fcose");
  const motionRef = useRef({ reducedMotion, isMobile });
  motionRef.current = { reducedMotion, isMobile };
  const lodRef = useRef<Lod>(lodFor(1, edges.length));
  // 전체 배치의 노드 위치(포커스 방사형 위치는 담지 않는다). 모드 전환·재배치 때 남는 노드는 여기서 시작하고,
  // 포커스에서 나오면 이 위치로 돌아간다.
  const positionsRef = useRef<Positions>(new Map());
  const layoutRunningRef = useRef(false);
  // 포커스·범례로 숨기지 않은 노드 수(미니맵 표시 기준)
  const [shownNodes, setShownNodes] = useState(0);
  const minimapId = useId();
  const showMinimap = !isMobile && shownNodes > MINIMAP_MIN_NODES;

  // 테마가 바뀌면 색 계산을 다시 해야 하므로 요소 정의에 테마를 포함한다.
  const elements = useMemo(() => toElements(nodes, edges, groupIsolated), [nodes, edges, groupIsolated, theme]);
  const bundleCount = elements.bundled.size;
  // 보기 상태(선택·포커스·필터·근거 강조)는 이벤트 처리기와 배치에서도 최신 값을 읽는다.
  const viewState: ViewState = { selectionId: selection?.id ?? null, bundled: elements.bundled, focus, hidden, evidence, path };
  const viewRef = useRef(viewState);
  viewRef.current = viewState;
  // 숨겨진 캔버스(목록 보기)에서는 배치를 미뤘다가, 보이게 되어 크기가 정해지면 실행한다.
  const pendingLayoutRef = useRef<(() => void) | null>(null);

  /** 묶음 노드 위에 키보드·스크린리더용 버튼을 겹친다(캔버스 노드는 DOM이 아니므로). */
  const placeBundleButton = () => {
    const cy = cyRef.current;
    const button = bundleButtonRef.current;
    if (!cy || !button) return;
    const bundle = cy.getElementById(ISOLATED_BUNDLE_ID);
    if (bundle.empty() || !bundle.visible()) {
      button.hidden = true;
      return;
    }
    const { x, y } = bundle.renderedPosition();
    const size = Math.max(44, bundle.renderedOuterWidth());
    button.hidden = false;
    button.style.left = `${x - size / 2}px`;
    button.style.top = `${y - size / 2}px`;
    button.style.width = button.style.height = `${size}px`;
  };
  const placeBundleButtonRef = useRef(placeBundleButton);
  placeBundleButtonRef.current = placeBundleButton;

  // 1) 캔버스는 한 번만 만든다.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const cy = cytoscape({
      container,
      // 300노드 지도와 가장자리 묶음이 한 화면에 들어오도록(라벨·노드는 LOD가 화면 크기를 지킨다)
      minZoom: 0.1,
      maxZoom: 3,
      boxSelectionEnabled: false,
      selectionType: "single",
      autounselectify: true,
      pixelRatio: "auto",
      // 끌기·확대 중에는 직전 화면을 텍스처로 재사용해 큰 지도에서도 부드럽게 움직인다.
      textureOnViewport: true,
    });
    const unbind = bindInteractions(cy, {
      container,
      onTap: (target) => onSelectRef.current(target),
      hasEmphasis: () => Boolean(viewRef.current.selectionId || viewRef.current.evidence || viewRef.current.path),
      restore: () => void applyViewState(cy, viewRef.current),
      prefs: () => motionRef.current,
      // 포커스 중에 끈 위치는 전체 배치에 남기지 않는다(나오면 원래 자리로).
      onNodeMoved: (id, position) => void (!viewRef.current.focus && positionsRef.current.set(id, position)),
      lod: { get: () => lodRef.current, set: (lod) => void (lodRef.current = lod) },
      onLodChange: (lod) => cy.style(buildStyle(motionRef.current.isMobile, lod)),
    });
    let buttonFrame = 0;
    cy.on("viewport position style", () => {
      if (buttonFrame) return;
      buttonFrame = requestAnimationFrame(() => {
        buttonFrame = 0;
        if (!cy.destroyed()) placeBundleButtonRef.current();
      });
    });
    cyRef.current = cy;
    const observer = new ResizeObserver(() => {
      cy.resize();
      if (cy.width() <= 0 || cy.height() <= 0) return;
      const pending = pendingLayoutRef.current;
      pendingLayoutRef.current = null;
      if (pending) pending();
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      unbind();
      cancelAnimationFrame(buttonFrame);
      cy.stop(true, false);
      cy.elements().stop(true, false);
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // 2) 테마·화면 폭이 바뀌면 색만 다시 입힌다.
  useEffect(() => {
    cyRef.current?.style(buildStyle(isMobile, lodRef.current));
  }, [theme, isMobile]);

  /** 포커스 화면 여백: 위는 포커스 바(56 + 간격), 모바일은 좌우·아래를 좁혀 방사형 배치를 크게 보인다. */
  const focusInsets = (): Insets =>
    motionRef.current.isMobile ? { top: 80, right: 16, bottom: 16, left: 16 } : { top: 80, right: FIT_PADDING, bottom: FIT_PADDING, left: FIT_PADDING };

  /** 전체 화면 맞춤 여백: 조작 도구가 있는 쪽(데스크톱 아래, 모바일 오른쪽)만 도구 폭(44 + 간격)을 비운다. */
  const fitInsets = (): Insets =>
    motionRef.current.isMobile
      ? { top: 16, right: FIT_PADDING, bottom: 16, left: 16 }
      : { top: 24, right: 24, bottom: FIT_PADDING, left: 24 };

  /** 지금 보이는 요소에 맞춘 화면. 포커스 중에는 방사형 배치의 라벨 자리를 알고 있으므로 그 값으로 맞춘다.
   *  경로 모드에서는 경로에 맞춘다(위는 경로 바, 모바일은 오른쪽 조작 도구를 비운다). 모바일 단계 목록은 경로 바에서 따로 연다. */
  const visibleViewport = (cy: Core) => {
    const route = pathElements(cy, viewRef.current.path);
    if (route.nonempty()) {
      const insets = motionRef.current.isMobile
        ? { top: 80, right: FIT_PADDING, bottom: 16, left: 16 }
        : { top: 80, right: FIT_PADDING, bottom: FIT_PADDING, left: FIT_PADDING };
      return fitViewport(cy, route, insets);
    }
    const shown = shownElements(cy);
    if (viewRef.current.focus) return fitViewport(cy, shown, focusInsets(), 1.4, FOCUS_LABEL_OVERHANG);
    // 가장자리 묶음은 배율에 따라 모델 크기·간격이 바뀌므로 맞춤 대상에서 빼고 그쪽 화면 자리만 비워 둔다.
    const bundle = shown.filter((e) => e.id() === ISOLATED_BUNDLE_ID);
    if (bundle.empty()) return fitViewport(cy, shown, fitInsets());
    const others = shown.difference(bundle);
    return fitViewport(cy, others, fitInsets(), 1.4, undefined, edgeNodeFootprint(edgeSide(cy, others)));
  };

  /** 포커스 방사형 목표 위치(전체 배치 위치를 기준으로 계산) */
  const focusTargets = (cy: Core) => {
    const focusNow = viewRef.current.focus;
    if (!focusNow) return new Map() as Positions;
    const pad = focusInsets();
    return focusPositions(cy, focusNow, positionsRef.current, { width: cy.width() - pad.left - pad.right, height: cy.height() - pad.top - pad.bottom });
  };

  /** 노드를 목표 위치로 옮기고, 옮긴 배치에 맞춘 화면으로 카메라를 함께 옮긴다. 동작 줄이기에서는 즉시. */
  const moveNodesTo = (cy: Core, targets: Positions) => {
    const moving = cy.nodes().filter((n) => targets.has(n.id()));
    const current: Positions = new Map(moving.toArray().map((n) => [n.id(), { ...(n as NodeSingular).position() }] as const));
    cy.stop(true, false);
    moving.stop(true, false);
    // 목표 배치에서 맞출 화면을 재고 되돌린다(같은 동기 구간이라 화면에 그려지지 않는다).
    moving.positions((n) => targets.get(n.id())!);
    const viewport = visibleViewport(cy);
    if (motionRef.current.reducedMotion) {
      cy.viewport(viewport);
      return;
    }
    moving.positions((n) => current.get(n.id())!);
    const duration = msVar("graph-layout");
    const easing = easingVar("standard");
    moving.forEach((node) => void node.animate({ position: targets.get(node.id())! }, { duration, easing }));
    cy.animate({ ...viewport, duration, easing });
  };

  // 3) 데이터·배치 방식이 바뀌면 요소를 교체하고 배치한다.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const remembered = positionsRef.current;
    cy.batch(() => {
      cy.elements().remove();
      cy.add(elements.definitions);
    });
    lodRef.current = lodFor(cy.zoom(), cy.edges().length);
    cy.style(buildStyle(isMobile, lodRef.current));

    // 기업 로고 글리프는 비동기로 만들어 붙인다(같은 로고는 캐시).
    let cancelled = false;
    cy.nodes('[kind = "company"]').forEach((node) => {
      const source = nodes.find((n) => n.id === node.id());
      const fill = node.data("fill") as string;
      void companyGlyph({ logoUrl: source?.logoUrl, name: source?.label ?? node.id(), color: glyphColor(fill) }).then((url) => {
        if (!cancelled && url && !node.removed()) node.data("glyph", url);
      });
    });

    let frame = 0;
    let cancelReveal = () => {};
    const run = () => {
      if (cancelled || cy.destroyed()) return;
      // 숨김(포커스·필터)과 관계없이 전체를 배치한 뒤 보기 상태를 다시 입히고, 보이는 요소에 맞춘다.
      const empty: ViewState = { selectionId: null, bundled: elements.bundled, focus: null, hidden: NO_HIDDEN, evidence: null, path: null };
      applyViewState(cy, empty);
      layoutRunningRef.current = true;
      const placement = placeNodes(cy, layoutName, isMobile, remembered, elements.bundled.size > 0 ? ISOLATED_BUNDLE_ID : undefined);
      layoutRunningRef.current = false;
      positionsRef.current = new Map(placement.final);
      const emphasized = applyViewState(cy, viewRef.current);
      // 포커스 중이면 남은 노드는 전체 배치 대신 방사형 자리로 간다(전체 배치 위치는 기억해 둔다).
      const radial = focusTargets(cy);
      radial.forEach((position, id) => {
        placement.final.set(id, position);
        cy.getElementById(id).position(position);
      });
      const target = visibleViewport(cy);
      // 묶음은 맞춘 배율에서의 크기로 비워 둔 가장자리 자리에 놓는다.
      const bundle = cy.getElementById(ISOLATED_BUNDLE_ID);
      if (bundle.nonempty()) {
        const position = placeEdgeNode(cy, bundle, isMobile, target.zoom);
        positionsRef.current.set(ISOLATED_BUNDLE_ID, position);
        if (!radial.has(ISOLATED_BUNDLE_ID)) placement.final.set(ISOLATED_BUNDLE_ID, position);
      }
      // 포커스·경로 화면은 그 전체를 보여 주는 것이 목적이라 선택으로 카메라를 옮기지 않는다.
      const follow = (collection: cytoscape.Collection) => {
        if (!viewRef.current.focus && !viewRef.current.path && collection.nonempty()) focusCamera(cy, collection, "center", motionRef.current);
      };
      if (motionRef.current.reducedMotion) {
        cy.viewport(target);
        follow(emphasized);
        return;
      }
      cancelReveal = revealPlacement(cy, placement, target, remembered, () => {
        if (!cancelled) follow(applyViewState(cy, viewRef.current));
      });
    };
    const settle = () => {
      frame = requestAnimationFrame(() => {
        if (cancelled || cy.destroyed()) return;
        cy.resize();
        if (cy.width() <= 0 || cy.height() <= 0) pendingLayoutRef.current = run;
        else run();
      });
    };
    void document.fonts.ready.then(() => !cancelled && settle());
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      cancelReveal();
      pendingLayoutRef.current = null;
      if (!cy.destroyed()) {
        cy.stop(true, false);
        cy.nodes().stop(true, true);
      }
    };
    // nodes는 elements와 같이 바뀐다. isMobile·layoutName이 바뀌면 다시 배치한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements, layoutName, isMobile]);

  // 4) 보기 상태(선택·포커스·필터·근거 강조·경로)를 입힌다. 카메라는 바뀐 것에 따라 움직인다.
  const selectionKey = selection ? `${selection.kind}:${selection.id}` : null;
  const focusKey = focus ? `${focus.id}:${focus.hops}` : null;
  const hiddenKey = [...hidden].sort().join(",");
  const evidenceKey = evidence ? `${evidence.evidenceId}:${evidence.issueId ?? ""}` : null;
  const pathKey = path ? `${path.from},${path.to}:${path.edgeIds.join(",")}` : null;
  const previousRef = useRef({ selectionKey, focusKey, evidenceKey, pathKey, elements });
  // 가운데 이동 요청(사이드바)은 선택·포커스 해제와 같은 렌더에 오지 않을 수 있다(주소 갱신이 한 박자 늦다).
  // 요청한 노드가 선택될 때까지 기억해 두고, 선택 카메라 대신 다시 적용한다.
  const pendingCenterRef = useRef<string | null>(null);
  /** 노드를 화면 가운데로, 최소 CENTER_ZOOM까지 확대해 옮긴다. 포커스·경로에서 나오는 중이면 노드가
   *  전체 배치 자리로 움직이는 중이므로 그 목표 위치(positionsRef)를 쓴다. */
  const centerNode = (cy: Core, id: string) => {
    const node = cy.getElementById(id);
    if (node.empty() || cy.width() <= 0) return;
    const at = positionsRef.current.get(id) ?? (node as NodeSingular).position();
    const zoom = Math.min(cy.maxZoom(), Math.max(cy.zoom(), CENTER_ZOOM));
    moveCamera(cy, { zoom, pan: { x: cy.width() / 2 - at.x * zoom, y: cy.height() / 2 - at.y * zoom } }, motionRef.current.reducedMotion, "slow");
  };
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const previous = previousRef.current;
    previousRef.current = { selectionKey, focusKey, evidenceKey, pathKey, elements };
    const emphasized = applyViewState(cy, viewRef.current);
    placeBundleButtonRef.current();
    setShownNodes(shownElements(cy).nodes().length);
    // 새 요소는 배치가 끝난 뒤 카메라를 맞춘다(배치 effect가 처리).
    if (layoutRunningRef.current || previous.elements !== elements) return;
    if (previous.focusKey !== focusKey) {
      // 포커스 진입·범위 변경: 남은 노드를 방사형으로 옮긴다. 해제: 전체 배치 위치로 되돌린다(재배치 없음).
      // 포커스에서 경로로 바로 넘어오면 전체 배치로 돌아가며 경로에 맞춘다(visibleViewport).
      moveNodesTo(cy, focus ? focusTargets(cy) : positionsRef.current);
    } else if (previous.pathKey !== pathKey) {
      // 경로 진입: 경로에 맞춘다. 해제: 보이는 전체에 맞춘다.
      moveCamera(cy, visibleViewport(cy), motionRef.current.reducedMotion, "slow");
    } else if ((previous.selectionKey !== selectionKey || previous.evidenceKey !== evidenceKey) && emphasized.nonempty()) {
      focusCamera(cy, emphasized, "center", motionRef.current);
    }
    if (pendingCenterRef.current && pendingCenterRef.current === selection?.id) {
      centerNode(cy, pendingCenterRef.current);
      pendingCenterRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionKey, focusKey, hiddenKey, evidenceKey, pathKey, elements]);

  // 4-1) 가운데 이동 요청(사이드바). 이미 그 노드가 선택돼 있으면(같은 기업을 다시 고름) 바로 옮기고,
  // 아니면 지금 옮긴 뒤 선택이 도착하면 4)에서 한 번 더 맞춘다(선택 카메라가 덮어쓰지 않도록).
  const centerSeq = centerOn?.seq ?? 0;
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !centerOn || layoutRunningRef.current) return;
    centerNode(cy, centerOn.id);
    pendingCenterRef.current = selection?.id === centerOn.id ? null : centerOn.id;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerSeq]);

  // 5) 미니맵: 보이는 노드가 기준을 넘는 데스크톱에서만 만들고, 조건이 사라지거나 해제되면 없앤다.
  useEffect(() => {
    const cy = cyRef.current;
    if (!showMinimap || !cy) return;
    return attachMinimap(cy, minimapId);
  }, [showMinimap, minimapId]);

  const selectedLabel = (() => {
    if (!selection) return "";
    if (selection.id === ISOLATED_BUNDLE_ID) return isolatedBundleLabel(bundleCount);
    if (selection.kind === "node") return nodes.find((n) => n.id === selection.id)?.label ?? "";
    const edge = edges.find((e) => e.id === selection.id);
    return edge ? `${edge.summary} 연결선` : "";
  })();

  const zoomBy = (factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    const level = Math.min(cy.maxZoom(), Math.max(cy.minZoom(), cy.zoom() * factor));
    const at = { x: cy.width() / 2, y: cy.height() / 2 };
    if (reducedMotion) cy.zoom({ level, renderedPosition: at });
    else {
      // 가운데를 기준으로 확대: pan도 같이 계산해 함께 움직인다.
      const pan = cy.pan();
      const ratio = level / cy.zoom();
      cy.stop(true, false).animate({ zoom: level, pan: { x: at.x - (at.x - pan.x) * ratio, y: at.y - (at.y - pan.y) * ratio }, duration: msVar("normal"), easing: easingVar("standard") });
    }
  };
  const fit = () => {
    const cy = cyRef.current;
    if (!cy || cy.nodes().empty()) return;
    moveCamera(cy, visibleViewport(cy), reducedMotion, "slow");
  };

  const viewToggles = (
    <Button
        variant="ghost"
        size="sm"
        aria-pressed={layoutName === "dagre"}
        onClick={() => setLayoutName((l) => (l === "dagre" ? "fcose" : "dagre"))}
      className="justify-start aria-pressed:bg-surface-selected aria-pressed:font-semibold"
    >
      {layoutName === "dagre" ? <GitBranch aria-hidden="true" /> : <Network aria-hidden="true" />}
      흐름 순으로 정렬
    </Button>
  );

  return (
    <div className={cn("relative flex min-h-0 flex-col overflow-hidden", className)}>
      <div ref={containerRef} role="img" aria-label={ariaLabel} data-graph-canvas="" className="min-h-0 flex-1 touch-none bg-surface-base" />
      {bundleCount > 0 && (
        <button
          ref={bundleButtonRef}
          type="button"
          hidden
          aria-label={`${isolatedBundleLabel(bundleCount)} 보기`}
          onClick={() => onSelect({ kind: "node", id: ISOLATED_BUNDLE_ID })}
          onFocus={() => {
            // 키보드로 왔는데 묶음이 화면 밖이면 카메라를 옮겨 보이게 한다.
            const cy = cyRef.current;
            const bundle = cy?.getElementById(ISOLATED_BUNDLE_ID);
            if (!cy || !bundle || bundle.empty()) return;
            const { x, y } = bundle.renderedPosition();
            if (x < 0 || y < 0 || x > cy.width() || y > cy.height()) focusCamera(cy, bundle, "center", motionRef.current);
          }}
          className="absolute rounded-full opacity-0 focus-visible:opacity-100 focus-visible:outline-3 focus-visible:outline-offset-4 focus-visible:outline-graph-focus-ring"
        />
      )}
      <p className="sr-only" aria-live="polite">
        {selection ? `${selectedLabel} 선택됨` : ""}
      </p>
      {showMinimap && (
        // 포인터 전용 조망(G7). 확장이 썸네일·보이는 영역·입력 덮개를 이 안에 채운다. 키보드 대체는 도구 막대.
        <div
          id={minimapId}
          aria-hidden="true"
          data-graph-minimap=""
          className={cn(
            "absolute right-3 bottom-3 h-[128px] w-[192px] overflow-hidden rounded-lg bg-surface-raised shadow-overlay",
            "[&_.cytoscape-navigatorView]:rounded-sm [&_.cytoscape-navigatorView]:border-2 [&_.cytoscape-navigatorView]:border-brand-primary [&_.cytoscape-navigatorView]:bg-brand-primary/10",
            "[&_.cytoscape-navigatorOverlay]:absolute [&_.cytoscape-navigatorOverlay]:inset-0 [&_.cytoscape-navigatorOverlay]:cursor-pointer [&.mouseover-view_.cytoscape-navigatorOverlay]:cursor-grab",
          )}
        />
      )}
      {isMobile ? (
        <div className="absolute right-3 bottom-3 flex flex-col gap-2">
          <RoundTool label="확대" onClick={() => zoomBy(1.25)}>
            <Plus aria-hidden="true" />
          </RoundTool>
          <RoundTool label="축소" onClick={() => zoomBy(0.8)}>
            <Minus aria-hidden="true" />
          </RoundTool>
          <RoundTool label="화면에 맞추기" onClick={fit}>
            <Maximize2 aria-hidden="true" />
          </RoundTool>
          {!minimalToolbar && (
            <Popover
              label="지도 보기 더보기"
              side="left"
              align="end"
              trigger={
                <button type="button" aria-label="더보기: 지도 보기 방식" className={roundToolClass}>
                  <MoreHorizontal className="size-5" aria-hidden="true" />
                </button>
              }
            >
              <div className="flex flex-col gap-1">{viewToggles}</div>
            </Popover>
          )}
        </div>
      ) : (
        <div className="pointer-events-none absolute right-3 bottom-3 left-3 flex items-end">
          <div className="pointer-events-auto flex items-center gap-1 rounded-sm bg-surface-raised p-0.5 shadow-overlay">
            <Tooltip content="확대">
              <Button variant="ghost" size="icon" aria-label="확대" onClick={() => zoomBy(1.25)}>
                <Plus aria-hidden="true" />
              </Button>
            </Tooltip>
            <Tooltip content="축소">
              <Button variant="ghost" size="icon" aria-label="축소" onClick={() => zoomBy(0.8)}>
                <Minus aria-hidden="true" />
              </Button>
            </Tooltip>
            <Tooltip content="화면에 맞추기">
              <Button variant="ghost" size="icon" aria-label="화면에 맞추기" onClick={fit}>
                <Maximize2 aria-hidden="true" />
              </Button>
            </Tooltip>
            {!minimalToolbar && (
              <>
                <span className="mx-1 h-6 w-px bg-border-subtle" aria-hidden="true" />
                {viewToggles}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const roundToolClass =
  "pressable flex size-11 items-center justify-center rounded-full bg-surface-raised text-text-primary shadow-overlay hover:bg-surface-sunken [&_svg]:size-5";

function RoundTool({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-label={label} onClick={onClick} className={roundToolClass}>
      {children}
    </button>
  );
}
