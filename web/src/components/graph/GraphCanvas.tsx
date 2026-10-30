import {
  useContext,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  GraphAppearanceContext,
  defaultAppearance,
  appearanceColors,
  styleGraph,
} from './graph-appearance';
import { createPortal } from 'react-dom';
import GraphLegend from './GraphLegend';
import { themeColor, useColorTheme } from '@/util/theme-color';
import {
  Graph,
  type GraphData,
  type IElementEvent,
  type NodeData,
} from '@antv/g6';
import type { GraphResponse } from '@/types/map/graph';
import { isSelectableRelation } from '@/types/map/relation';
import GraphIcon from './GraphIcon';
import {
  emptyView,
  isolatedIssues,
  readModeEntry,
  saveModeEntry,
  type GraphView,
  type LegendKey,
  sameViewport,
  MAP_LAYOUT_REVISION,
} from './graph-view';
import { focusNeighborhood, graphSummary, toG6Data } from './graph-model';
import { arrangeFlow, arrangeFocus } from './graph-arrange';
import { applyGraphReading } from './graph-readability';
import {
  cameraMotion,
  EDGE_ANIMATION,
  followRoundLogos,
  NODE_ANIMATION,
  type CameraMove,
} from './graph-motion';
import GraphMobileTools from './GraphMobileTools';
import MapEmptyState from './MapEmptyState';
import type { PersonalScope } from '@/types/map';
import {
  fitFootprint,
  fitZoom,
  freeViewport,
  type Rect,
} from './graph-geometry';

const noHighlightedEdges: string[] = [];

export default function GraphCanvas({
  data,
  selectedId: selected = null,
  onSelect,
  focusId = null,
  focusHops = 1,
  focusLayout = false,
  flow = false,
  onFlowChange,
  highlightedEdgeIds = noHighlightedEdges,
  selectedEdgeId = null,
  isolateSelection = false,
  evidenceMode = false,
  onSelectEdge,
  connectionPath = false,
  memoryOwner = 'public',
  onOpenIsolated,
  centerRequest = null,
  filterHost,
  tutorialPhase,
  tutorialTargetId,
  tutorialCenterId,
  tutorialLocked = false,
  tutorialCameraEnabled = false,
  tutorialShowNeighborhood = false,
  onTutorialAction,
  onPersonalFilter,
  onMarket,
}: {
  data: GraphResponse;
  filterHost?: HTMLElement | null;
  tutorialPhase?: 'pan' | 'zoom';
  tutorialTargetId?: string;
  tutorialCenterId?: string;
  tutorialLocked?: boolean;
  tutorialCameraEnabled?: boolean;
  tutorialShowNeighborhood?: boolean;
  onTutorialAction?: (action: 'pan' | 'zoom') => void;
  onPersonalFilter?: (scope: PersonalScope) => void;
  onMarket?: () => void;
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  focusId?: string | null;
  focusHops?: 1 | 2;
  /** D-GRP-07b 포커스 모드: 포커스 노드의 1·2단계 이웃만 남기고 방사형으로 다시 배치한다. */
  focusLayout?: boolean;
  /** D-GRP-01 [흐름 순으로 정렬]: 사건→기업·선행→후속 방향으로 왼쪽에서 오른쪽에 층을 나눈다. */
  flow?: boolean;
  /** 주면 확대·축소 묶음에 [흐름 순으로 정렬] 토글을 둔다. */
  onFlowChange?: (flow: boolean) => void;
  highlightedEdgeIds?: string[];
  selectedEdgeId?: string | null;
  /** 근거에 연결선이 없을 때 사건만 강조한다. */
  isolateSelection?: boolean;
  /** 근거 강조가 활성화되면 이전 hover가 무관한 연결을 강조하지 않는다. */
  evidenceMode?: boolean;
  onSelectEdge?: (id: string) => void;
  connectionPath?: boolean;
  memoryOwner?: string;
  onOpenIsolated?: () => void;
  /** 내 종목 사이드바에서 고른 기업. seq가 바뀔 때마다 그 노드를 화면 가운데로 옮긴다. */
  centerRequest?: { id: string; seq: number } | null;
}) {
  const suppliedAppearance =
    useContext(GraphAppearanceContext) ?? defaultAppearance;
  const { variant, theme, preview } = suppliedAppearance;
  // A parent render with equivalent theme values must not destroy the renderer.
  const appearance = useMemo(
    () => ({ variant, theme, preview }),
    [variant, theme, preview],
  );
  const colors = appearanceColors(appearance);
  // 화면 모드가 바뀌면 그래프는 그대로 두고 토큰 색(themeColor)만 다시 읽는다. 카메라·선택이 그대로 남는다.
  const colorTheme = useColorTheme();
  const tutorialAction = useEffectEvent((action: 'pan' | 'zoom') =>
    onTutorialAction?.(action),
  );
  const currentTutorialPhase = useEffectEvent(() => tutorialPhase);
  const isTutorial = useEffectEvent(() =>
    Boolean(tutorialPhase || tutorialCenterId),
  );
  const viewKey = `${memoryOwner}:${data.metadata.mode}`;
  const [viewState, setViewState] = useState(() => ({
    key: viewKey,
    view: readModeEntry(memoryOwner, data.metadata.mode)?.view ?? emptyView(),
  }));
  let view = viewState.view;
  if (viewState.key !== viewKey) {
    view = readModeEntry(memoryOwner, data.metadata.mode)?.view ?? emptyView();
    setViewState({ key: viewKey, view });
  }
  function changeView(next: GraphView) {
    setViewState({ key: viewKey, view: next });
    const saved = readModeEntry(memoryOwner, data.metadata.mode);
    saveModeEntry(memoryOwner, data.metadata.mode, {
      url: saved?.url ?? `/?mode=${data.metadata.mode}`,
      view: { ...next, camera: saved?.view.camera },
    });
  }
  function toggleKind(key: LegendKey) {
    if (
      (key === 'company' || key === 'issue') &&
      !view.hidden.includes(key) &&
      view.hidden.includes(key === 'company' ? 'issue' : 'company')
    )
      return;
    changeView({
      ...view,
      hidden: view.hidden.includes(key)
        ? view.hidden.filter((item) => item !== key)
        : [...view.hidden, key],
    });
  }
  const container = useRef<HTMLDivElement>(null);
  const dragPractice = useRef<{ x: number; y: number; moved: number } | null>(
    null,
  );
  const instance = useRef<Graph | null>(null);
  const [zoom, setZoom] = useState(1);
  const [dragAnchor, setDragAnchor] = useState<{ x: number; y: number } | null>(
    null,
  );
  const [tutorialMarker, setTutorialMarker] = useState<{
    x: number;
    y: number;
    size: number;
  } | null>(null);

  const drawing = useRef(Promise.resolve());
  const lastFocused = useRef<string | null>(null);
  const tutorialCentered = useRef<string | undefined>(undefined);
  const hovered = useRef<string | null>(null);
  const hoveredEdge = useRef<string | null>(null);
  const readingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const renderedData = useRef<ReturnType<typeof toG6Data> | null>(null);
  const appliedStates = useRef({
    rendered: null as ReturnType<typeof toG6Data> | null,
    states: new Map<string, string>(),
  });
  const lastArrangement = useRef('map');
  const [renderError, setRenderError] = useState(false);
  const reading = useEffectEvent(() => {
    const graph = instance.current;
    const base = renderedData.current;
    if (!graph || graph.destroyed || !base) return;
    drawing.current = drawing.current
      .then(async () => {
        if (
          instance.current !== graph ||
          graph.destroyed ||
          renderedData.current !== base
        )
          return;
        const path = new Set(highlightedEdgeIds);
        for (const edge of base.edges ?? [])
          if (path.has(String(edge.id))) {
            path.add(String(edge.source));
            path.add(String(edge.target));
          }
        await applyGraphReading(graph, base, data, {
          zoom: graph.getZoom(),
          anchor: evidenceMode ? selected : (hovered.current ?? selected),
          edge: evidenceMode ? null : (hoveredEdge.current ?? selectedEdgeId),
          focus: focusId,
          path,
        });
      })
      .catch(() => {
        if (!graph.destroyed) setRenderError(true);
      });
  });
  const scheduleReading = useEffectEvent(() => {
    if (readingTimer.current !== null) clearTimeout(readingTimer.current);
    readingTimer.current = setTimeout(() => {
      readingTimer.current = null;
      reading();
    }, 140);
  });
  const pinchEnabled = useEffectEvent(
    () =>
      !isTutorial() ||
      currentTutorialPhase() === 'zoom' ||
      tutorialCameraEnabled,
  );
  const interactionEnabled = useEffectEvent(
    () => !tutorialLocked && !tutorialPhase && !tutorialCenterId,
  );
  const [hoveredIssue, setHoveredIssue] = useState<string | null>(null);
  const fitPending = useRef(false);
  /** [맞춤] 버튼으로 생긴 맞춤만 움직인다(첫 그리기·크기 변경 맞춤은 바로). */
  const fitRequested = useRef(false);
  const defaultZoomPending = useRef(false);
  const followFit = useRef(true);
  const minimapShown = useRef(false);
  // D-GRP-01/03: 상세 패널을 제외한 지도 영역의 중앙에 선택 노드를 유지한다.
  const centerTarget = useRef<string | null>(null);
  const previousSelected = useRef<string | null>(null);
  const preservePositions = useRef(false);
  // 화면 모드 전환처럼 색만 바뀌는 다시 그리기는 지금 노드 위치를 한 번 그대로 쓴다.
  const keepPositionsOnce = useRef(false);
  const [centerSequence, setCenterSequence] = useState(0);
  const syncTutorialMarker = useEffectEvent(() => {
    const graph = instance.current;
    const host = container.current;
    if (
      tutorialPhase === 'pan' &&
      host &&
      host.clientWidth &&
      host.clientHeight
    ) {
      // Five o'clock: 30 degrees right of down, 25% of the shorter viewport edge.
      const distance = Math.min(host.clientWidth, host.clientHeight) * 0.25;
      const x = host.clientWidth / 2 + distance * 0.5;
      const y = host.clientHeight / 2 + (distance * Math.sqrt(3)) / 2;
      setDragAnchor((old) => (old?.x === x && old.y === y ? old : { x, y }));
    }
    const node = renderedData.current?.nodes?.find(
      (item) => item.id === tutorialTargetId,
    );
    if (!graph || graph.destroyed || !node) {
      setTutorialMarker(null);
      return;
    }
    const x = Number(node.style?.x);
    const y = Number(node.style?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const point = graph.getViewportByCanvas([x, y]);
    const rawSize = node.style?.size;
    const size = Number(Array.isArray(rawSize) ? rawSize[0] : rawSize) || 40;
    const next = {
      x: point[0],
      y: point[1],
      size: size * graph.getZoom() + 20,
    };
    setTutorialMarker((old) =>
      old?.x === next.x && old.y === next.y && old.size === next.size
        ? old
        : next,
    );
  });
  // 지금 적용한 배치(원래 지도·포커스·흐름 순). 바뀌면 화면을 새 배치에 맞춘다.
  function handleNodeSelect(id: string | null) {
    if (tutorialPhase || (tutorialLocked && id !== tutorialTargetId)) return;
    if (id === '__isolated__') return onOpenIsolated?.();
    // 이미 선택한 노드를 다시 눌러도 수동 이동한 지도에서 중앙으로 돌아온다.
    centerTarget.current = id;
    if (id) {
      preservePositions.current = false;
      followFit.current = false;
      fitPending.current = false;
      setCenterSequence((sequence) => sequence + 1);
    }
    onSelect?.(id);
  }
  const selectNode = useEffectEvent(handleNodeSelect);
  const selectEdge = useEffectEvent((id: string) => {
    if (tutorialPhase || tutorialLocked) return;
    if (data.edges.some((edge) => edge.id === id && isSelectableRelation(edge)))
      onSelectEdge?.(id);
  });
  const [retry, setRetry] = useState(0);
  const stats = graphSummary(data);
  const nodeKinds = new Map(data.nodes.map((node) => [node.id, node.kind]));
  const personal = data.metadata.mode === 'personal';
  const focusedNodes = focusNeighborhood(data, focusId, focusHops);
  const selectedNode = data.nodes.find((n) => n.id === selected);
  // D-GRP-01: hover changes presentation only, never selection, layout or viewport.
  const syncVisualStates = useEffectEvent(
    async (graph: Graph, rendered: ReturnType<typeof toG6Data>) => {
      const visibleIds = new Set(
        rendered.nodes?.map((node) => String(node.id)),
      );
      // 마우스를 올린 노드가 우선이고, 없으면 클릭해 선택한 노드의 연결을 계속 강조한다.
      const anchor =
        (evidenceMode ? null : hovered.current) ??
        (selected && nodeKinds.has(selected) ? selected : null);
      const active =
        anchor &&
        visibleIds.has(anchor) &&
        (!focusId || focusedNodes.has(anchor))
          ? anchor
          : null;
      const relatedNodes = new Set(active ? [active] : []);
      const relatedEdges = new Set<string>();
      if (active && !isolateSelection) {
        for (const edge of rendered.edges ?? []) {
          const source = String(edge.source);
          const target = String(edge.target);
          if (
            (source === active || target === active) &&
            (!focusId || (focusedNodes.has(source) && focusedNodes.has(target)))
          ) {
            relatedNodes.add(source);
            relatedNodes.add(target);
            relatedEdges.add(String(edge.id));
          }
        }
      }
      // 포커스 모드에서는 연결 없는 노드가 이미 숨겨지므로, 남은 1·2단계 노드·연결선을 흐리게 하지 않는다.
      const dimRest = !(focusLayout && focusId);
      const states: Record<string, string[]> = {};
      for (const node of rendered.nodes ?? []) {
        const id = String(node.id);
        states[id] = active
          ? [
              id === active
                ? id === hovered.current
                  ? 'hovered'
                  : 'related'
                : relatedNodes.has(id)
                  ? 'related'
                  : 'inactive',
            ].filter((state) => dimRest || state !== 'inactive')
          : [];
        if (tutorialLocked && !tutorialPhase && !tutorialShowNeighborhood)
          states[id] = id === tutorialTargetId ? [] : ['inactive'];
        if (id === selected && (!tutorialLocked || tutorialShowNeighborhood))
          states[id].push('selected');
        if (id === tutorialTargetId) states[id].push('tutorial');
      }
      for (const edge of rendered.edges ?? []) {
        const id = String(edge.id);
        states[id] = active
          ? [relatedEdges.has(id) ? 'related' : 'inactive'].filter(
              (state) => dimRest || state !== 'inactive',
            )
          : [];
        if (tutorialLocked && !tutorialShowNeighborhood)
          states[id] = ['inactive'];
        if (id === selectedEdgeId && !tutorialLocked)
          states[id].push('selected');
      }
      // 노드가 많으면 모든 요소의 상태를 다시 넣는 일이 hover마다 가장 무겁다. 바뀐 요소만 넘긴다.
      const applied = appliedStates.current;
      if (applied.rendered !== rendered) {
        applied.rendered = rendered;
        applied.states.clear();
      }
      const changed: Record<string, string[]> = {};
      for (const [id, next] of Object.entries(states)) {
        const key = next.join(' ');
        if (applied.states.get(id) === key) continue;
        applied.states.set(id, key);
        changed[id] = next;
      }
      if (Object.keys(changed).length) await graph.setElementState(changed);
      scheduleReading();
    },
  );
  const hoverSyncQueued = useRef(false);
  const hoverClearTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hoverNode = useEffectEvent((id: string | null) => {
    if (hoverClearTimer.current !== null) {
      clearTimeout(hoverClearTimer.current);
      hoverClearTimer.current = null;
    }
    if (tutorialLocked) return;
    if (hovered.current === id) return;
    hovered.current = id;
    setHoveredIssue(
      data.nodes.find((node) => node.id === id && node.kind === 'issue')
        ?.label ?? null,
    );
    const graph = instance.current;
    if (!graph) return;
    // 마우스가 빠르게 지나가면 쌓인 hover를 하나씩 그리지 않고, 차례가 왔을 때의 hover만 그린다.
    if (hoverSyncQueued.current) return;
    hoverSyncQueued.current = true;
    drawing.current = drawing.current
      .then(async () => {
        hoverSyncQueued.current = false;
        if (
          graph.destroyed ||
          instance.current !== graph ||
          !renderedData.current
        )
          return;
        await syncVisualStates(graph, renderedData.current);
      })
      .catch(() => {
        hoverSyncQueued.current = false;
        if (!graph.destroyed) setRenderError(true);
      });
  });
  const leaveNode = useEffectEvent((id: string) => {
    // A late leave from the previous node must not clear the new node's hover.
    if (hovered.current !== id) return;
    setHoveredIssue(null);
    // 노드 사이를 옮겨 다닐 때 전체 흐림을 풀었다 다시 거는 일을 막도록, 해제는 잠깐 기다린다.
    if (hoverClearTimer.current !== null) clearTimeout(hoverClearTimer.current);
    hoverClearTimer.current = setTimeout(() => {
      hoverClearTimer.current = null;
      if (hovered.current === id) hoverNode(null);
    }, 120);
  });
  const isArranged = useEffectEvent(
    () => (focusLayout && Boolean(focusId)) || flow,
  );
  const retainFocus = useEffectEvent(() => {
    lastFocused.current = focusId;
  });
  async function centerSelectedNode(
    graph: Graph,
    rendered: ReturnType<typeof toG6Data>,
  ) {
    const host = container.current;
    const target = rendered.nodes?.find(
      (node) =>
        node.id === centerTarget.current && node.style?.visibility !== 'hidden',
    );
    if (!host || !target || !host.clientWidth || !host.clientHeight) return;
    // Desktop rails already reduce the host width. Mobile details overlay the
    // canvas, so use the part above the sheet instead of centering behind it.
    const hostRect = host.getBoundingClientRect();
    const sheet = document.querySelector<HTMLElement>(
      '[data-screen-id="M-GRP-01"]',
    );
    const rect = sheet?.getClientRects().length
      ? sheet.getBoundingClientRect()
      : null;
    const safe = freeViewport(
      host.clientWidth,
      host.clientHeight,
      rect
        ? [
            {
              x: rect.left - hostRect.left,
              y: rect.top - hostRect.top,
              width: rect.width,
              height: rect.height,
            },
          ]
        : [],
    );
    if (safe.width < 40 || safe.height < 40) return;
    // Use the circle/diamond position, rather than label/halo bounds.
    const point = graph.getViewportByCanvas([
      Number(target.style?.x ?? 0),
      Number(target.style?.y ?? 0),
    ]);
    followFit.current = false;
    fitPending.current = false;
    await graph.translateBy(
      [safe.x + safe.width / 2 - point[0], safe.y + safe.height / 2 - point[1]],
      cameraMotion('select'),
    );
  }
  async function fitVisibleGraph(
    graph: Graph,
    ids?: Set<string>,
    maxZoom = 1.5,
    // 사용자가 맞춤을 누르거나 배치를 바꾼 경우만 움직인다. 처음 그릴 때·크기가 바뀔 때는 바로 맞춘다.
    animate: false | Extract<CameraMove, 'fit' | 'layout'> = false,
  ) {
    const host = container.current;
    if (!host || graph.destroyed || !host.clientWidth || !host.clientHeight)
      return;
    const hostRect = host.getBoundingClientRect();
    const root = host.parentElement;
    const overlays = [
      ...(root?.querySelectorAll<HTMLElement>(
        '.relationship-zoom,.relationship-source,.relationship-selection,.graph-overview',
      ) ?? []),
      ...document.querySelectorAll<HTMLElement>('[data-screen-id="M-GRP-01"]'),
    ];
    const obstacles: Rect[] = overlays
      .filter((el) => el.getClientRects().length && !el.closest('.hidden'))
      .map((el) => {
        const r = el.getBoundingClientRect();
        return {
          x: r.left - hostRect.left,
          y: r.top - hostRect.top,
          width: r.width,
          height: r.height,
        };
      });
    // The plugin creates its DOM asynchronously. Reserve its known geometry
    // on the first fit as well, before it has a measurable container.
    if (minimapShown.current)
      obstacles.push({
        x: host.clientWidth - 192,
        y: host.clientHeight - 64 - 128,
        width: 192,
        height: 128,
      });
    // Desktop layouts can be wider than the browser. Reserve the clipped
    // portion too, rather than fitting nodes behind horizontal page overflow.
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;
    if (viewportWidth > 0 && hostRect.right > viewportWidth)
      obstacles.push({
        x: viewportWidth - hostRect.left,
        y: 0,
        width: hostRect.right - viewportWidth,
        height: host.clientHeight,
      });
    if (viewportHeight > 0 && hostRect.bottom > viewportHeight)
      obstacles.push({
        x: 0,
        y: viewportHeight - hostRect.top,
        width: host.clientWidth,
        height: hostRect.bottom - viewportHeight,
      });
    if (hostRect.left < 0)
      obstacles.push({
        x: 0,
        y: 0,
        width: -hostRect.left,
        height: host.clientHeight,
      });
    if (hostRect.top < 0)
      obstacles.push({
        x: 0,
        y: 0,
        width: host.clientWidth,
        height: -hostRect.top,
      });
    const safe = freeViewport(host.clientWidth, host.clientHeight, obstacles);
    if (safe.width < 40 || safe.height < 40) return;
    const footprints = graph
      .getNodeData()
      .filter(
        (node) =>
          node.style?.visibility !== 'hidden' &&
          (!ids || ids.has(String(node.id))),
      )
      .map(fitFootprint);
    if (!footprints.length) return;
    const fit = fitZoom(footprints, safe, maxZoom);
    const motion = animate ? cameraMotion(animate) : false;
    // G6 5.1.1은 확대와 이동을 함께 움직이는 transform을 Graph에 공개하지 않아 viewport에서 직접 부른다.
    const viewport = (
      graph as unknown as {
        context?: {
          viewport?: {
            transform(
              options: {
                mode: 'relative';
                scale: number;
                translate: [number, number];
              },
              animation: typeof motion,
            ): Promise<void>;
          };
        };
      }
    ).context?.viewport;
    if (motion && viewport) {
      // 움직이는 transform은 화면 가운데를 기준으로 확대하므로,
      // 끝난 뒤 맞춤 중심이 빈 영역 가운데에 오도록 카메라 위치를 직접 계산한다.
      const zoom = graph.getZoom();
      const [width, height] = graph.getSize();
      const camera = graph.getCanvasByViewport([width / 2, height / 2]);
      const target = [
        fit.center[0] - (safe.x + safe.width / 2 - width / 2) / fit.zoom,
        fit.center[1] - (safe.y + safe.height / 2 - height / 2) / fit.zoom,
      ];
      await viewport.transform(
        {
          mode: 'relative',
          scale: fit.zoom / zoom,
          translate: [
            (camera[0] - target[0]) * zoom,
            (camera[1] - target[1]) * zoom,
          ],
        },
        motion,
      );
      return;
    }
    await graph.zoomTo(fit.zoom, false);
    if (graph.destroyed) return;
    const center = graph.getViewportByCanvas(fit.center);
    await graph.translateBy(
      [
        safe.x + safe.width / 2 - center[0],
        safe.y + safe.height / 2 - center[1],
      ],
      false,
    );
  }
  const [neighborhoodRequest, setNeighborhoodRequest] = useState<{
    id: string;
  } | null>(null);
  /** 접힌 사건에서 Shift+Enter를 누르면 먼저 펼쳐 그리고, 그 그리기가 끝난 뒤 이웃 맞춤을 한다. */
  const pendingNeighborhood = useRef<string | null>(null);
  const zoomNeighborhood = useEffectEvent((id: string) => {
    const graph = instance.current;
    if (!interactionEnabled() || !graph || graph.destroyed) return;
    const base = renderedData.current;
    if (!base) return;
    const drawn =
      base.nodes?.some(
        (node) => node.id === id && node.style?.visibility !== 'hidden',
      ) || base.edges?.some((edge) => edge.id === id);
    if (!drawn) return;
    const current = graph;
    centerTarget.current = null;
    followFit.current = false;
    fitPending.current = false;
    drawing.current = drawing.current
      .then(async () => {
        if (!current.destroyed) {
          await fitVisibleGraph(current, neighborhoodIds(base, id), 1.8, 'fit');
          scheduleReading();
        }
      })
      .catch(() => {
        if (!current.destroyed) setRenderError(true);
      });
  });
  /** 키보드 Shift+Enter. 지금 그려지지 않은(접힌) 노드면 먼저 골라 펼치고, 다음 그리기 뒤에 맞춘다. */
  function requestNeighborhood(id: string) {
    const drawn = renderedData.current?.nodes?.some(
      (node) => node.id === id && node.style?.visibility !== 'hidden',
    );
    if (!drawn && data.nodes.some((node) => node.id === id)) {
      pendingNeighborhood.current = id;
      handleNodeSelect(id);
      return;
    }
    setNeighborhoodRequest({ id });
  }
  function neighborhoodIds(base: GraphData, id: string) {
    const ids = new Set([id]);
    const edge = base.edges?.find((e) => e.id === id);
    if (edge) {
      ids.add(String(edge.source));
      ids.add(String(edge.target));
    }
    for (const e of base.edges ?? [])
      if (
        e.style?.visibility !== 'hidden' &&
        (e.source === id || e.target === id)
      ) {
        ids.add(String(e.source));
        ids.add(String(e.target));
      }
    return ids;
  }
  useEffect(() => {
    if (neighborhoodRequest) zoomNeighborhood(neighborhoodRequest.id);
  }, [neighborhoodRequest]);

  // 상태별(관련·선택·튜토리얼 등) 선·노드 색. 화면 모드를 바꾸면 그래프를 다시 만들지 않고 이 값만 바꾼다.
  const stateStyles = useEffectEvent(() => ({
    edge: {
      animation: EDGE_ANIMATION,
      state: {
        related: {
          lineWidth: appearance.variant === 'improved' ? 3.5 : 3,
          stroke:
            appearance.variant === 'improved'
              ? colors.selected
              : themeColor('ink'),
          strokeOpacity: 1,
        },
        inactive: { strokeOpacity: 0.2 },
        selected: {
          lineWidth: appearance.variant === 'improved' ? 3.5 : 3,
          stroke:
            appearance.variant === 'improved'
              ? colors.selected
              : themeColor('ink'),
          strokeOpacity: 1,
        },
      },
    },
    node: {
      animation: NODE_ANIMATION,
      state: {
        tutorial: {
          opacity: 1,
          halo: true,
          stroke: themeColor('ink'),
          lineDash: [6, 4],
          haloStroke: themeColor('ink'),
          haloOpacity: 1,
          haloFill: 'transparent',
          haloLineDash: [5, 4],
          haloLineWidth: 4,
          haloStrokeOpacity: 1,
          lineWidth: 3,
        },
        related: {
          opacity: 1,
          lineWidth: 1.4,
          labelFill: themeColor('ink'),
        },
        inactive: { opacity: 0.35 },
        hovered: {
          opacity: 1,
          lineWidth: 2,
          halo: true,
          haloStroke: themeColor('ink'),
          haloFill: 'transparent',
          labelFill: themeColor('ink'),
        },
        selected: {
          lineWidth: 2,
          halo: true,
          haloStroke: themeColor('ink'),
          haloFill: 'transparent',
          // G6 기본 테마의 selected는 이름표를 12px로 줄인다. 노드에 정한 크기·굵기를 그대로 쓴다.
          labelFontSize: (datum: NodeData) =>
            Number(datum.style?.labelFontSize ?? 12),
          labelFontWeight: (datum: NodeData) =>
            datum.style?.labelFontWeight ?? 700,
        },
      },
    },
  }));
  // 화면 모드가 바뀌면 같은 그래프·카메라에서 색만 다시 읽어 그린다(82번).
  // 처음 그릴 자료도 그때의 화면 모드로 만든다. 화면 모드는 그래프를 다시 만드는 조건이 아니다.
  const initialData = useEffectEvent((width: number, height: number) =>
    styleGraph(toG6Data(data, width, height), appearance),
  );
  const applyColorTheme = useEffectEvent(() => {
    const graph = instance.current;
    if (!graph || graph.destroyed) return;
    const { node, edge } = stateStyles();
    graph.setNode(node);
    graph.setEdge(edge);
    keepPositionsOnce.current = true;
    syncSelection();
  });
  const themeKey = `${colorTheme}:${theme}`;
  const appliedTheme = useRef(themeKey);
  useEffect(() => {
    if (appliedTheme.current === themeKey) return;
    appliedTheme.current = themeKey;
    applyColorTheme();
  }, [themeKey]);
  const syncSelection = useEffectEvent(() => {
    const graph = instance.current;
    const host = container.current;
    if (!graph || !host) return;
    // Serialize G6 drawing; selecting/closing never recreates the graph or viewport.
    const arrangeFocusNow = focusLayout && Boolean(focusId);
    const arrangement = arrangeFocusNow
      ? `focus:${focusId}:${focusHops}`
      : flow
        ? 'flow'
        : 'map';
    drawing.current = drawing.current
      .then(async () => {
        if (graph.destroyed) return;
        const rendered = styleGraph(
          toG6Data(
            data,
            host.clientWidth,
            host.clientHeight,
            selected ?? focusId,
            [
              ...(tutorialTargetId ? [tutorialTargetId] : []),
              ...data.edges
                .filter((edge) => highlightedEdgeIds.includes(edge.id))
                .flatMap((edge) => [edge.source, edge.target]),
              ...(arrangeFocusNow ? focusedNodes : []),
            ],
            connectionPath && highlightedEdgeIds.length
              ? new Set(
                  data.edges
                    .filter((e) => highlightedEdgeIds.includes(e.id))
                    .flatMap((e) => [e.source, e.target]),
                )
              : focusedNodes,
          ),
          appearance,
        );
        rendered.edges = rendered.edges?.map((edge) =>
          highlightedEdgeIds.includes(String(edge.id))
            ? {
                ...edge,
                style: {
                  ...edge.style,
                  stroke: connectionPath
                    ? appearance.variant === 'improved'
                      ? colors.selected
                      : themeColor('ink')
                    : themeColor('ink'),
                  strokeOpacity: 1,
                  lineWidth: connectionPath ? 3 : 4.5,
                },
              }
            : edge,
        );
        if (
          onOpenIsolated &&
          isolatedIssues(data).length &&
          !view.hidden.includes('issue')
        )
          rendered.nodes?.push({
            id: '__isolated__',
            type: 'circle',
            style: {
              x: host.clientWidth - 65,
              y: host.clientHeight / 2,
              size: 48,
              fill: themeColor('soft'),
              stroke: themeColor('ink'),
              labelText: `연결 없는 사건 ${stats.disconnected}건`,
              labelPlacement: 'bottom',
              iconText: String(stats.disconnected),
              cursor: 'pointer',
            },
          });
        const pathNodes = new Set(
          data.edges
            .filter((edge) => highlightedEdgeIds.includes(edge.id))
            .flatMap((edge) => [edge.source, edge.target]),
        );
        // 근거에 연결선이 없어 사건만 강조할 때도 범례로 숨긴 사건을 드러낸다(15번).
        if (isolateSelection && selected) pathNodes.add(selected);
        // 배치가 바뀌면(포커스 진입·해제, 흐름 순 켜기·끄기) 이전 위치를 유지하지 않고 새 배치 전체를 화면에 맞춘다.
        // 포커스 진입·단계 바꾸기·해제와 흐름 순 켜기·끄기에서는 노드가 지금 자리에서 새 자리로 옮겨 간다(프로토타입 G2).
        const morphFrom =
          arrangement !== lastArrangement.current && cameraMotion('layout')
            ? renderedData.current
            : null;
        if (arrangement !== lastArrangement.current) {
          lastArrangement.current = arrangement;
          preservePositions.current = false;
          // 정렬 좌표는 현재 캔버스 크기로 다시 계산된다. 상세 패널이나
          // 창 크기가 바뀌어도 새 배치가 잘리지 않도록 화면 맞춤을 이어 간다.
          followFit.current = true;
          centerTarget.current = null;
          fitPending.current = true;
        }
        const arrangedHidden = new Set<string>();
        if (arrangeFocusNow && focusId) {
          const focused = arrangeFocus(
            rendered,
            data,
            focusId,
            focusHops,
            host.clientWidth,
            host.clientHeight,
          );
          rendered.nodes = focused.nodes;
          focused.hidden.forEach((id) => arrangedHidden.add(id));
        } else if (flow) {
          rendered.nodes = arrangeFlow(
            rendered,
            data,
            host.clientWidth,
            host.clientHeight,
          );
        }
        if (arrangement !== 'map') arrangedHidden.add('__isolated__');
        // Closing details changes the available width, but must not rearrange
        // the graph the user just centered (including its surrounding nodes).
        if (
          arrangement === 'map' &&
          (preservePositions.current || keepPositionsOnce.current) &&
          renderedData.current
        ) {
          const positions = new Map(
            renderedData.current.nodes?.map((node) => [node.id, node.style]),
          );
          rendered.nodes = rendered.nodes?.map((node) => {
            const position = positions.get(node.id);
            return position
              ? {
                  ...node,
                  style: { ...node.style, x: position.x, y: position.y },
                }
              : node;
          });
        }
        keepPositionsOnce.current = false;
        const relationTypes = new Map(
          data.edges.map((edge) => [edge.id, edge.relationType]),
        );
        const hiddenNodes = new Set([
          ...data.nodes
            .filter(
              (node) =>
                view.hidden.includes(node.kind) && !pathNodes.has(node.id),
            )
            .map((node) => node.id),
          ...arrangedHidden,
        ]);
        rendered.nodes = rendered.nodes?.map((node) => ({
          ...node,
          style: {
            ...node.style,
            visibility: hiddenNodes.has(String(node.id)) ? 'hidden' : 'visible',
          },
        }));
        rendered.edges = rendered.edges?.map((edge) => ({
          ...edge,
          style: {
            ...edge.style,
            visibility:
              !highlightedEdgeIds.includes(String(edge.id)) &&
              (hiddenNodes.has(String(edge.source)) ||
                hiddenNodes.has(String(edge.target)) ||
                view.hidden.includes(relationTypes.get(String(edge.id))!))
                ? 'hidden'
                : 'visible',
          },
        }));
        // 옮겨 갈 노드는 먼저 이전 자리에 그리고, 맞춤 단계에서 목표 자리로 옮긴다.
        const morphTargets: Record<string, [number, number]> = {};
        const previous = new Map(
          morphFrom?.nodes?.map((node) => [node.id, node.style]),
        );
        graph.setData(
          morphFrom
            ? {
                ...rendered,
                nodes: rendered.nodes?.map((node) => {
                  const from = previous.get(node.id);
                  const { x, y } = node.style ?? {};
                  if (
                    !from ||
                    typeof from.x !== 'number' ||
                    typeof from.y !== 'number' ||
                    typeof x !== 'number' ||
                    typeof y !== 'number' ||
                    (from.x === x && from.y === y)
                  )
                    return node;
                  morphTargets[String(node.id)] = [x, y];
                  return {
                    ...node,
                    style: { ...node.style, x: from.x, y: from.y },
                  };
                }),
              }
            : rendered,
        );
        await graph.draw();
        const visibleCount =
          rendered.nodes?.filter((node) => node.style?.visibility !== 'hidden')
            .length ?? 0;
        minimapShown.current = visibleCount > 60 && host.clientWidth >= 768;
        const minimapEdges = new Set(
          rendered.edges
            ?.filter((edge) => edge.style?.visibility !== 'hidden')
            .map((edge) => String(edge.id)),
        );
        graph.setPlugins(
          minimapShown.current
            ? [
                {
                  type: 'minimap',
                  key: 'graph-overview',
                  size: [192, 128],
                  position: 'right-bottom',
                  // G6 passes this value to classList.add: it must be one token.
                  className: 'graph-overview',
                  filter: (id: string, kind: string) =>
                    kind === 'node'
                      ? !hiddenNodes.has(id)
                      : minimapEdges.has(id),
                },
              ]
            : [],
        );
        if (graph.destroyed) return;
        renderedData.current = rendered;
        await syncVisualStates(graph, rendered);
        if (
          !arrangeFocusNow &&
          focusId &&
          focusId !== lastFocused.current &&
          rendered.nodes?.some((node) => node.id === focusId)
        )
          await graph.focusElement(focusId, cameraMotion('select'));
        lastFocused.current = focusId;
        // Resize changes layout coordinates. Center only after the new draw,
        // never on the previous layout before the detail rail has resized it.
        if (centerTarget.current) await centerSelectedNode(graph, rendered);
        const pending = pendingNeighborhood.current;
        if (
          pending &&
          rendered.nodes?.some(
            (node) =>
              node.id === pending && node.style?.visibility !== 'hidden',
          )
        ) {
          pendingNeighborhood.current = null;
          centerTarget.current = null;
          await fitVisibleGraph(
            graph,
            neighborhoodIds(rendered, pending),
            1.8,
            'fit',
          );
        }
        // 노드 이동이 모델 좌표를 먼저 바꾸므로, 바로 이어서 재는 맞춤은 새 배치를 기준으로 한다.
        const moving = Object.keys(morphTargets).length
          ? graph.translateElementTo(morphTargets, true)
          : null;
        if (moving) followRoundLogos(graph, Object.keys(morphTargets), moving);
        if (fitPending.current) {
          fitPending.current = false;
          const animate = fitRequested.current;
          fitRequested.current = false;
          await fitVisibleGraph(
            graph,
            undefined,
            undefined,
            moving ? 'layout' : animate ? 'fit' : false,
          );
        }
        await moving;
        if (defaultZoomPending.current) {
          defaultZoomPending.current = false;
          await graph.zoomTo(0.53, false);
          setZoom(0.53);
          followFit.current = false;
        }
        if (
          tutorialCenterId &&
          tutorialCentered.current !== tutorialCenterId &&
          rendered.nodes?.some((node) => node.id === tutorialCenterId)
        ) {
          await graph.focusElement(tutorialCenterId, false);
          followFit.current = false;
        }
        tutorialCentered.current = tutorialCenterId;
        syncTutorialMarker();
        scheduleReading();
      })
      .catch(() => {
        if (!graph.destroyed) setRenderError(true);
      });
  });
  useEffect(() => {
    if (previousSelected.current && !selected) preservePositions.current = true;
    previousSelected.current = selected;
    centerTarget.current = selected;
    if (selected) {
      preservePositions.current = false;
      followFit.current = false;
      fitPending.current = false;
    }
  }, [selected]);
  useEffect(() => {
    if (!centerRequest) return;
    preservePositions.current = false;
    followFit.current = false;
    fitPending.current = false;
    centerTarget.current = centerRequest.id;
    syncSelection();
  }, [centerRequest]);
  useEffect(() => {
    syncSelection();
  }, [
    selected,
    centerSequence,
    tutorialTargetId,
    tutorialCenterId,
    selectedEdgeId,
    isolateSelection,
    evidenceMode,
    focusId,
    focusHops,
    focusLayout,
    flow,
    highlightedEdgeIds,
    connectionPath,
    view.hidden,
  ]);
  // 튜토리얼 단계의 잠금·카메라·이웃 표시는 그려진 데이터를 바꾸지 않는다. 지도 전체를 다시 그리지 않고 상태만 맞춘다.
  const syncTutorialStates = useEffectEvent(() => {
    const graph = instance.current;
    if (!graph) return;
    drawing.current = drawing.current
      .then(async () => {
        const rendered = renderedData.current;
        if (graph.destroyed || instance.current !== graph || !rendered) return;
        await syncVisualStates(graph, rendered);
        syncTutorialMarker();
      })
      .catch(() => {
        if (!graph.destroyed) setRenderError(true);
      });
  });
  useEffect(() => {
    syncTutorialStates();
  }, [
    tutorialPhase,
    tutorialLocked,
    tutorialCameraEnabled,
    tutorialShowNeighborhood,
  ]);
  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let disposed = false;
    let graph: Graph | null = null;
    let observer: ResizeObserver | null = null;
    let resizeFrame: number | null = null;
    const clearHover = () => {
      hoveredEdge.current = null;
      setHoveredIssue(null);
      hoverNode(null);
      scheduleReading();
    };
    let pointerStart: {
      x: number;
      y: number;
      graphX: number;
      graphY: number;
      allowed: boolean;
    } | null = null;
    let wheelPending = false;
    let previousZoom = 1;
    // 누른 뒤 일정 거리 이상 움직였으면 지도 이동이다. 손을 뗄 때 생기는 클릭으로 노드·연결을 고르지 않는다.
    let dragged = false;
    const pointerDown = (event: PointerEvent) => {
      if (!graph || event.button !== 0) return;
      const bounds = host.getBoundingClientRect();
      const position = graph.getPosition();
      wheelPending = false;
      dragged = false;
      pointerStart = {
        x: event.clientX,
        y: event.clientY,
        graphX: position[0],
        graphY: position[1],
        allowed:
          currentTutorialPhase() === 'pan' &&
          Math.hypot(
            event.clientX - bounds.left - bounds.width / 2,
            event.clientY - bounds.top - bounds.height * 0.72,
          ) <= 64,
      };
    };
    const pointerMove = (event: PointerEvent) => {
      if (
        pointerStart &&
        Math.hypot(
          event.clientX - pointerStart.x,
          event.clientY - pointerStart.y,
        ) > 4
      ) {
        followFit.current = false;
        centerTarget.current = null;
        dragged = true;
      }
    };
    const pointerUp = (event: PointerEvent) => {
      if (
        pointerStart?.allowed &&
        graph &&
        !graph.destroyed &&
        Math.hypot(
          event.clientX - pointerStart.x,
          event.clientY - pointerStart.y,
        ) >= 24
      ) {
        const position = graph.getPosition();
        if (
          Math.hypot(
            position[0] - pointerStart.graphX,
            position[1] - pointerStart.graphY,
          ) >= 12
        )
          tutorialAction('pan');
      }
      pointerStart = null;
    };
    const stopFollowing = (event: WheelEvent) => {
      if (event.deltaY !== 0 && currentTutorialPhase() === 'zoom')
        wheelPending = true;
      followFit.current = false;
      centerTarget.current = null;
    };
    const viewportChanged = () => {
      if (centerTarget.current) {
        syncSelection();
        return;
      }
      if (followFit.current) {
        fitPending.current = true;
        syncSelection();
      }
    };
    host.addEventListener('pointerleave', clearHover);
    host.addEventListener('pointerdown', pointerDown);
    host.addEventListener('pointermove', pointerMove);
    window.addEventListener('pointerup', pointerUp);
    host.addEventListener('wheel', stopFollowing, { passive: true });
    window.addEventListener('zoop:graph-viewport-change', viewportChanged);
    hovered.current = null;
    renderedData.current = null;
    preservePositions.current = false;
    const graphMode = data.metadata.mode;
    const rememberCamera = () => {
      if (!graph || disposed || graph.destroyed || instance.current !== graph)
        return;
      // 포커스·흐름 순 배치의 카메라는 원래 지도 좌표와 맞지 않으므로 기억하지 않는다.
      if (lastArrangement.current !== 'map') return;
      const position = graph.getPosition();
      const saved = readModeEntry(memoryOwner, graphMode);
      saveModeEntry(memoryOwner, graphMode, {
        url: saved?.url ?? `/?mode=${graphMode}`,
        view: {
          ...(saved?.view ?? emptyView()),
          camera: {
            zoom: graph.getZoom(),
            position: [position[0], position[1]],
            size: [host.clientWidth, host.clientHeight],
            layout: MAP_LAYOUT_REVISION,
          },
        },
      });
    };
    async function mount() {
      await document.fonts.ready;
      if (disposed || !host) return;
      setRenderError(false);
      setZoom(1);
      lastFocused.current = null;
      graph = new Graph({
        container: host,
        width: host.clientWidth,
        height: host.clientHeight,
        // 카메라 이동만 움직인다(graph-motion.ts). G6 5는 이 값이 false면 화면 이동 애니메이션도 모두 끄므로 켜 두고,
        // 노드·연결선(stateStyles)과 휠 확대·끌기는 따로 꺼서 지금처럼 바로 반응하게 한다.
        animation: true,
        data: initialData(host.clientWidth, host.clientHeight),
        // D-GRP-01: 빈 곳뿐 아니라 노드·연결 위에서 끌어도 지도를 움직인다(노드 자체는 옮기지 않는다).
        behaviors: [
          { type: 'drag-canvas', enable: true, animation: false },
          { type: 'zoom-canvas', animation: false },
          {
            type: 'zoom-canvas',
            key: 'map-pinch-zoom',
            trigger: ['pinch'],
            animation: false,
            enable: () => pinchEnabled(),
          },
        ],
        zoomRange: [0.01, 4],
        ...stateStyles(),
      });
      graph.on('node:dblclick', (event: IElementEvent) =>
        zoomNeighborhood(event.target.id),
      );
      graph.on('edge:dblclick', (event: IElementEvent) =>
        zoomNeighborhood(event.target.id),
      );
      graph.on('edge:pointerenter', (event: IElementEvent) => {
        if (!interactionEnabled()) return;
        hoveredEdge.current = event.target.id;
        setHoveredIssue(null);
        scheduleReading();
      });
      graph.on('edge:pointerleave', () => {
        hoveredEdge.current = null;
        setHoveredIssue(null);
        scheduleReading();
      });
      graph.on('node:click', (event: IElementEvent) => {
        if (!dragged) selectNode(event.target.id);
      });
      graph.on('node:pointerenter', (event: IElementEvent) =>
        hoverNode(event.target.id),
      );
      graph.on('node:pointerleave', (event: IElementEvent) =>
        leaveNode(event.target.id),
      );
      graph.on('canvas:pointerleave', clearHover);
      graph.on('canvas:click', () => {
        if (!dragged) selectNode(null);
      });
      graph.on('edge:click', (event: IElementEvent) => {
        if (!dragged) selectEdge(event.target.id);
      });
      graph.on('aftertransform', () => {
        if (!graph || disposed) return;
        try {
          const nextZoom = graph.getZoom();
          setZoom(nextZoom);
          // 이름표 크기와 겹침은 배율에만 달려 있어서, 끌어서 옮기기만 하면 다시 재지 않는다.
          if (Math.abs(nextZoom - previousZoom) > 0.0001) scheduleReading();
          if (
            wheelPending &&
            currentTutorialPhase() === 'zoom' &&
            Math.abs(nextZoom - previousZoom) > 0.0001
          ) {
            wheelPending = false;
            tutorialAction('zoom');
          }
          previousZoom = nextZoom;
          syncTutorialMarker();
          rememberCamera();
        } catch {
          /* transform may fire before canvas init */
        }
      });
      try {
        await graph.render();
      } catch {
        if (!disposed) setRenderError(true);
      }
      if (disposed) return;
      const saved = isTutorial()
        ? undefined
        : readModeEntry(memoryOwner, graphMode)?.view.camera;
      // 창 크기가 달라졌으면 예전 위치가 화면 밖을 가리킬 수 있어 화면에 맞춰 연다.
      // 포커스·흐름 순으로 열면 기억한 원래 지도 카메라를 쓰지 않고 새 배치에 맞춘다.
      const arranged = isArranged();
      const camera =
        !preview &&
        !arranged &&
        saved &&
        sameViewport(saved.size, host.clientWidth, host.clientHeight)
          ? saved
          : null;
      followFit.current = !camera;
      fitPending.current = !camera;
      defaultZoomPending.current = !camera;
      if (camera) {
        retainFocus();
        await graph.zoomTo(camera.zoom, false);
        // 저장한 값은 getPosition()(캔버스 원점의 화면 위치)이다. translateTo는 기준이 달라
        // 노드가 화면 밖으로 밀려나므로, 지금 위치와의 차이만큼 옮겨 같은 화면을 되살린다.
        const current = graph.getPosition();
        await graph.translateBy(
          [camera.position[0] - current[0], camera.position[1] - current[1]],
          false,
        );
      }
      instance.current = graph;
      syncSelection();
      let lastSize = [host.clientWidth, host.clientHeight];
      observer = new ResizeObserver(() => {
        if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => {
          resizeFrame = null;
          if (!graph || disposed || graph.destroyed) return;
          if (host.clientWidth <= 0 || host.clientHeight <= 0) return;
          const [width, height] = [host.clientWidth, host.clientHeight];
          const origin = preservePositions.current
            ? graph.getViewportByCanvas([0, 0])
            : null;
          graph.setSize(width, height);
          // Some renderers shift their projection on resize. Preserve screen
          // pixels when the detail rail closes, rather than recentering the view.
          if (origin) {
            const next = graph.getViewportByCanvas([0, 0]);
            if (origin[0] !== next[0] || origin[1] !== next[1])
              void graph.translateBy(
                [origin[0] - next[0], origin[1] - next[1]],
                false,
              );
          }
          // 선택 노드의 중앙 이동은 아래 syncSelection의 새 좌표로 처리한다.
          if (
            !centerTarget.current &&
            !preservePositions.current &&
            !followFit.current &&
            (width !== lastSize[0] || height !== lastSize[1])
          )
            void graph.translateBy(
              [(width - lastSize[0]) / 2, (height - lastSize[1]) / 2],
              false,
            );
          lastSize = [width, height];
          if (followFit.current) fitPending.current = true;
          syncSelection();
        });
      });
      observer.observe(host);
    }
    void mount().catch(() => {
      if (!disposed) setRenderError(true);
    });
    return () => {
      rememberCamera();
      if (readingTimer.current !== null) {
        clearTimeout(readingTimer.current);
        readingTimer.current = null;
      }
      if (hoverClearTimer.current !== null) {
        clearTimeout(hoverClearTimer.current);
        hoverClearTimer.current = null;
      }
      disposed = true;
      host.removeEventListener('pointerleave', clearHover);
      host.removeEventListener('pointerdown', pointerDown);
      host.removeEventListener('pointermove', pointerMove);
      window.removeEventListener('pointerup', pointerUp);
      host.removeEventListener('wheel', stopFollowing);
      window.removeEventListener('zoop:graph-viewport-change', viewportChanged);
      observer?.disconnect();
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      graph?.destroy();
      instance.current = null;
    };
  }, [data, retry, memoryOwner, variant, preview]);
  async function control(action: 'in' | 'out' | 'fit') {
    const graph = instance.current;
    if (!graph || graph.destroyed) return;
    try {
      centerTarget.current = null;
      if (action === 'fit') {
        preservePositions.current = false;
        followFit.current = true;
        fitPending.current = true;
        fitRequested.current = true;
        setCenterSequence((sequence) => sequence + 1);
      } else {
        followFit.current = false;
        await graph.zoomTo(
          Math.max(
            0.01,
            Math.min(4, graph.getZoom() * (action === 'in' ? 1.2 : 1 / 1.2)),
          ),
          cameraMotion('zoom'),
        );
        onTutorialAction?.('zoom');
      }
    } catch {
      setRenderError(true);
    }
  }
  return (
    <div
      className="relationship-canvas [&_.graph-overview]:rounded-panel [&_.graph-overview]:border [&_.graph-overview]:border-panel-line [&_.graph-overview]:bg-zoop-paper [&_.graph-overview]:shadow-lg [&_.graph-overview]:bottom-16! [&_.graph-overview]:top-auto!"
      data-testid="graph-canvas"
      onWheel={(event) => {
        if (tutorialPhase === 'zoom' && event.deltaY !== 0)
          void control(event.deltaY < 0 ? 'in' : 'out');
      }}
    >
      <div
        ref={container}
        // G6 writes an inline position: relative on its container, which would size the host by
        // its own canvas. Keep it pinned to the map surface so each new graph measures full size.
        className={`relationship-g6 absolute! inset-0 ${(tutorialLocked && !tutorialCameraEnabled) || tutorialPhase ? 'pointer-events-none' : ''} ${tutorialPhase ? 'opacity-35' : ''}`}
        data-tutorial-action={tutorialCameraEnabled ? 'move' : undefined}
        aria-disabled={Boolean(tutorialPhase)}
        role="img"
        aria-label={`${personal ? '내 종목' : '시장 전체'} 관계 지도: 기업 ${stats.company}개, 사건 ${stats.issue}개. 드래그로 이동하고 휠로 확대합니다.`}
      />
      {hoveredIssue && (
        <p
          role="tooltip"
          className="pointer-events-none absolute top-3 right-3 z-20 max-w-[min(22rem,65%)] rounded border border-panel-line bg-zoop-paper px-3 py-2 font-panel text-sm text-panel-ink shadow-sm break-words"
        >
          {hoveredIssue}
        </p>
      )}
      {filterHost ? (
        createPortal(
          <GraphLegend
            data={data}
            hidden={view.hidden}
            onToggle={toggleKind}
          />,
          filterHost,
        )
      ) : filterHost === undefined ? (
        <div className="absolute top-2 right-2 left-2 z-10 overflow-x-auto bg-zoop-paper p-1">
          <GraphLegend data={data} hidden={view.hidden} onToggle={toggleKind} />
        </div>
      ) : null}
      {stats.disconnected > 0 && !view.hidden.includes('issue') && (
        <button
          type="button"
          className="sr-only focus:not-sr-only focus:absolute focus:top-12 focus:right-3 focus:z-20 focus:bg-white focus:p-3"
          onClick={onOpenIsolated}
          disabled={Boolean(tutorialPhase)}
          aria-label={`연결 없는 사건 ${stats.disconnected}건 보기`}
        >
          {stats.disconnected}
          <span className="block">연결 없는 사건</span>
        </button>
      )}
      <div className="relationship-source [&_p]:break-keep">
        <p>SOURCE · {data.metadata.source}</p>
        <p>
          AS OF{' '}
          {new Intl.DateTimeFormat('sv-SE', {
            timeZone: 'Asia/Seoul',
            dateStyle: 'short',
            timeStyle: 'short',
          }).format(new Date(data.metadata.asOf))}{' '}
          KST
        </p>
      </div>
      {tutorialPhase === 'pan' && (
        <button
          className="absolute z-20 grid size-32 -translate-x-1/2 -translate-y-1/2 touch-none place-items-center rounded-full border-2 border-dashed border-zoop-ink bg-zoop-paper/75 px-3 text-center text-xs font-bold text-zoop-ink focus-visible:outline-4"
          style={{
            left: dragAnchor?.x ?? '62.5%',
            top: dragAnchor?.y ?? '71.65%',
          }}
          data-tutorial-action="move"
          aria-label="강조된 지도 이동 영역"
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            dragPractice.current = {
              x: event.clientX,
              y: event.clientY,
              moved: 0,
            };
          }}
          onPointerMove={(event) => {
            const previous = dragPractice.current;
            const graph = instance.current;
            if (!previous || !graph || graph.destroyed) return;
            const dx = event.clientX - previous.x;
            const dy = event.clientY - previous.y;
            previous.x = event.clientX;
            previous.y = event.clientY;
            previous.moved += Math.hypot(dx, dy);
            followFit.current = false;
            centerTarget.current = null;
            drawing.current = drawing.current.then(async () => {
              if (!graph.destroyed && instance.current === graph)
                await graph.translateBy([dx, dy], false);
            });
          }}
          onPointerUp={() => {
            const moved = dragPractice.current?.moved ?? 0;
            dragPractice.current = null;
            if (moved >= 24) {
              void drawing.current.then(() => onTutorialAction?.('pan'));
            }
          }}
          onPointerCancel={() => {
            dragPractice.current = null;
          }}
          onKeyDown={(event) => {
            const direction: Record<string, [number, number]> = {
              ArrowLeft: [-40, 0],
              ArrowRight: [40, 0],
              ArrowUp: [0, -40],
              ArrowDown: [0, 40],
            };
            const graph = instance.current;
            if (direction[event.key] && graph && !graph.destroyed) {
              event.preventDefault();
              followFit.current = false;
              void graph
                .translateBy(direction[event.key], false)
                .then(() => onTutorialAction?.('pan'));
            }
          }}
        >
          이 빈 공간을 누른 채 끌어 보세요
        </button>
      )}
      {tutorialTargetId && tutorialMarker && (
        <button
          type="button"
          aria-label={`강조된 ${data.nodes.find((node) => node.id === tutorialTargetId)?.label ?? ''} 노드 선택`}
          data-tutorial-action="node"
          className="absolute z-20 rounded-full border-2 border-dashed border-zoop-ink bg-transparent focus-visible:outline-4"
          style={{
            left: tutorialMarker.x,
            top: tutorialMarker.y,
            width:
              tutorialMarker.size *
              (data.nodes.find((node) => node.id === tutorialTargetId)?.kind ===
              'issue'
                ? 1.15
                : 1),
            height:
              tutorialMarker.size *
              (data.nodes.find((node) => node.id === tutorialTargetId)?.kind ===
              'issue'
                ? 1.15
                : 1),
            transform: 'translate(-50%, -50%)',
          }}
          onClick={() => onSelect?.(tutorialTargetId)}
        />
      )}
      <div
        className={`relationship-zoom z-20 ${tutorialPhase ? '' : 'max-md:left-auto! max-md:right-3! max-md:bottom-3! max-md:flex-col max-md:gap-2 max-md:border-0! max-md:bg-transparent! max-md:[&>button]:size-11! max-md:[&>button]:rounded-full! max-md:[&>button]:border! max-md:[&>button]:border-zoop-line! max-md:[&>button]:bg-zoop-paper! max-md:[&>button]:text-zoop-ink! max-md:[&>button]:shadow-sm'} ${tutorialPhase === 'zoom' ? 'tutorial-target' : ''}`}
        aria-label="지도 확대 조절"
      >
        {/* 마우스를 올리거나 키보드로 고르면 버튼 위에 이름을 보인다. 화면 낭독기는 aria-label을 읽는다. */}
        <button
          data-tutorial-action="zoom"
          onClick={() => void control('in')}
          aria-label="확대"
          className="group relative"
        >
          <GraphIcon name="plus" />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 -translate-x-1/2 rounded-[3px] bg-zoop-ink px-1.5 py-0.5 text-[11px] whitespace-nowrap text-zoop-paper opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
          >
            확대
          </span>
        </button>
        <button
          data-tutorial-action="zoom"
          onClick={() => void control('out')}
          aria-label="축소"
          className="group relative"
        >
          <GraphIcon name="minus" />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 -translate-x-1/2 rounded-[3px] bg-zoop-ink px-1.5 py-0.5 text-[11px] whitespace-nowrap text-zoop-paper opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
          >
            축소
          </span>
        </button>
        <button
          // 지도 움직이기 단계에서도 확대·축소와 같이 쓸 수 있다.
          data-tutorial-action="zoom"
          onClick={() => void control('fit')}
          aria-label="전체 그래프 맞춤"
          className="group relative"
        >
          <GraphIcon name="fit" />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 -translate-x-1/2 rounded-[3px] bg-zoop-ink px-1.5 py-0.5 text-[11px] whitespace-nowrap text-zoop-paper opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
          >
            전체 그래프 맞춤
          </span>
        </button>
        {onFlowChange && (
          <button
            type="button"
            aria-pressed={flow}
            disabled={focusLayout && Boolean(focusId)}
            title={
              focusLayout && focusId
                ? '포커스 모드에서는 흐름 순 정렬을 쓸 수 없어요. 전체 보기로 나온 뒤 켜 주세요.'
                : '사건에서 관련 기업, 선행 사건에서 후속 사건 방향으로 왼쪽에서 오른쪽에 정렬해요.'
            }
            onClick={() => onFlowChange(!flow)}
            className="max-md:hidden! w-auto! px-2! text-[13px] font-semibold whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:bg-zoop-soft aria-pressed:outline-[0.667px] aria-pressed:outline-zoop-ink"
          >
            흐름 순으로 정렬
          </button>
        )}
        {!tutorialPhase && (
          <GraphMobileTools
            flow={flow}
            onFlowChange={onFlowChange}
            focusActive={focusLayout && Boolean(focusId)}
          />
        )}
        <output className="max-md:sr-only text-[13px]!">
          {Math.round(zoom * 100)}% · 드래그로 이동 · 휠로 확대
        </output>
      </div>
      {selectedNode && (
        // 선택 안내는 화면에 띄우지 않고 보조 기술에만 알린다(선택 내용은 상세 패널이 보여 준다).
        <p className="relationship-selection sr-only" role="status">
          {selectedNode.label}
          {selectedNode.geography
            ? ` · ${selectedNode.geography === 'domestic' ? '국내' : '국제'}`
            : ''}
          {selectedNode.holding ? ' · 보유' : ''}
          {selectedNode.watch ? ' · 관심' : ''}
        </p>
      )}
      <MapEmptyState
        graph={data}
        onPersonalFilter={onPersonalFilter}
        onMarket={onMarket}
      />
      {renderError && (
        <div className="relationship-message" role="alert">
          그래프를 표시하지 못했습니다.
          <button
            data-tutorial-action="retry"
            onClick={() => setRetry((v) => v + 1)}
          >
            다시 시도
          </button>
        </div>
      )}
      <div
        className="relationship-accessible-nodes"
        aria-label="키보드로 기업·사건·연결선 선택"
        inert={Boolean(tutorialPhase)}
      >
        {data.nodes
          .filter((node) => !view.hidden.includes(node.kind))
          .map((node) => (
            <button
              key={node.id}
              data-tutorial-managed-disabled
              disabled={tutorialLocked && node.id !== tutorialTargetId}
              data-tutorial-action={
                node.id === tutorialTargetId ? 'node' : undefined
              }
              aria-pressed={selected === node.id}
              className={
                node.id === tutorialTargetId ? 'tutorial-target' : undefined
              }
              title="Shift+Enter로 연결된 이웃 맞춤 확대"
              onKeyDown={(event) => {
                if (event.key === 'Enter' && event.shiftKey) {
                  event.preventDefault();
                  requestNeighborhood(node.id);
                }
              }}
              onClick={() => handleNodeSelect(node.id)}
            >
              {node.kind === 'issue' ? '사건: ' : '기업: '}
              {node.label}
              {node.holding ? ' · 보유' : ''}
              {node.watch ? ' · 관심' : ''}
            </button>
          ))}
        {data.edges
          .filter(
            (edge) =>
              isSelectableRelation(edge) &&
              !view.hidden.includes(edge.relationType) &&
              [edge.source, edge.target].every((id) => {
                const kind = nodeKinds.get(id);
                return !kind || !view.hidden.includes(kind);
              }),
          )
          .map((edge) => (
            <button
              key={edge.id}
              data-tutorial-managed-disabled
              disabled={tutorialLocked}
              aria-pressed={selectedEdgeId === edge.id}
              title="Shift+Enter로 연결된 이웃 맞춤 확대"
              onKeyDown={(event) => {
                if (event.key === 'Enter' && event.shiftKey) {
                  event.preventDefault();
                  setNeighborhoodRequest({ id: edge.id });
                }
              }}
              onClick={() => onSelectEdge?.(edge.id)}
            >
              연결선:{' '}
              {data.nodes.find((node) => node.id === edge.source)?.label} –{' '}
              {data.nodes.find((node) => node.id === edge.target)?.label} ·{' '}
              {edge.relationType === 'SHARES_ISSUE' ? '사건 공유' : '후속 관계'}{' '}
              · {edge.summary}
            </button>
          ))}
      </div>
    </div>
  );
}
