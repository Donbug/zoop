import { useContext, useEffect, useEffectEvent, useRef, useState } from 'react';
import {
  GraphAppearanceContext,
  defaultAppearance,
  appearanceColors,
  styleGraph,
} from './graph-appearance';
import { createPortal } from 'react-dom';
import GraphLegend from './GraphLegend';
import { themeColor } from '@/util/theme-color';
import { Graph, type IElementEvent } from '@antv/g6';
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
} from './graph-view';
import { focusNeighborhood, graphSummary, toG6Data } from './graph-model';
import { freeViewport, nodeRect, type Rect } from './graph-geometry';

export default function GraphCanvas({
  data,
  selectedId: selected = null,
  onSelect,
  focusId = null,
  focusHops = 1,
  highlightedEdgeIds = [],
  selectedEdgeId = null,
  onSelectEdge,
  connectionPath = false,
  memoryOwner = 'public',
  onOpenIsolated,
  centerRequest = null,
  filterHost,
}: {
  data: GraphResponse;
  /** Render the one legend in the map toolbar, sharing this canvas visibility state. */
  filterHost?: HTMLElement | null;
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  focusId?: string | null;
  focusHops?: 1 | 2;
  highlightedEdgeIds?: string[];
  selectedEdgeId?: string | null;
  onSelectEdge?: (id: string) => void;
  connectionPath?: boolean;
  memoryOwner?: string;
  onOpenIsolated?: () => void;
  /** 내 종목 사이드바에서 고른 기업. seq가 바뀔 때마다 그 노드를 화면 가운데로 옮긴다. */
  centerRequest?: { id: string; seq: number } | null;
}) {
  const appearance = useContext(GraphAppearanceContext) ?? defaultAppearance;
  const colors = appearanceColors(appearance);
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
  const instance = useRef<Graph | null>(null);
  const [zoom, setZoom] = useState(1);
  const drawing = useRef(Promise.resolve());
  const lastFocused = useRef<string | null>(null);
  const hovered = useRef<string | null>(null);
  const [hoveredIssue, setHoveredIssue] = useState<string | null>(null);
  const fitPending = useRef(false);
  const followFit = useRef(true);
  const minimapShown = useRef(false);
  // 사이드바에서 고른 기업. 상세 패널이 열려 지도 크기가 바뀌어도 이 기업을 가운데에 둔다.
  const centerTarget = useRef<string | null>(null);
  const renderedData = useRef<ReturnType<typeof toG6Data> | null>(null);
  const selectNode = useEffectEvent((id: string | null) =>
    id === '__isolated__' ? onOpenIsolated?.() : onSelect?.(id),
  );
  const selectEdge = useEffectEvent((id: string) => {
    if (data.edges.some((edge) => edge.id === id && isSelectableRelation(edge)))
      onSelectEdge?.(id);
  });
  const [renderError, setRenderError] = useState(false);
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
        hovered.current ??
        (selected && nodeKinds.has(selected) ? selected : null);
      const active =
        anchor &&
        visibleIds.has(anchor) &&
        (!focusId || focusedNodes.has(anchor))
          ? anchor
          : null;
      const relatedNodes = new Set(active ? [active] : []);
      const relatedEdges = new Set<string>();
      if (active) {
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
            ]
          : [];
        if (id === selected) states[id].push('selected');
      }
      for (const edge of rendered.edges ?? []) {
        const id = String(edge.id);
        states[id] = active
          ? [relatedEdges.has(id) ? 'related' : 'inactive']
          : [];
        if (id === selectedEdgeId) states[id].push('selected');
      }
      await graph.setElementState(states);
    },
  );
  const hoverNode = useEffectEvent((id: string | null) => {
    if (hovered.current === id) return;
    hovered.current = id;
    setHoveredIssue(
      data.nodes.find((node) => node.id === id && node.kind === 'issue')
        ?.label ?? null,
    );
    const graph = instance.current;
    if (!graph) return;
    drawing.current = drawing.current
      .then(async () => {
        if (
          graph.destroyed ||
          instance.current !== graph ||
          !renderedData.current
        )
          return;
        await syncVisualStates(graph, renderedData.current);
      })
      .catch(() => {
        if (!graph.destroyed) setRenderError(true);
      });
  });
  const leaveNode = useEffectEvent((id: string) => {
    // A late leave from the previous node must not clear the new node's hover.
    if (hovered.current === id) hoverNode(null);
  });
  const retainFocus = useEffectEvent(() => {
    lastFocused.current = focusId;
  });
  useEffect(() => {
    if (!centerRequest) return;
    const graph = instance.current;
    if (!graph) return;
    drawing.current = drawing.current
      .then(async () => {
        if (graph.destroyed || instance.current !== graph) return;
        if (
          !renderedData.current?.nodes?.some(
            (node) => String(node.id) === centerRequest.id,
          )
        )
          return;
        // 사용자가 고른 위치이므로 자동 맞춤을 멈춘다.
        followFit.current = false;
        centerTarget.current = centerRequest.id;
        await graph.focusElement(centerRequest.id, false);
      })
      .catch(() => {
        if (!graph.destroyed) setRenderError(true);
      });
  }, [centerRequest]);
  async function fitVisibleGraph(graph: Graph) {
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
    const rects = graph
      .getNodeData()
      .filter((node) => node.style?.visibility !== 'hidden')
      .map(nodeRect);
    if (!rects.length) return;
    const left = Math.min(...rects.map((r) => r.x)),
      top = Math.min(...rects.map((r) => r.y));
    const right = Math.max(...rects.map((r) => r.x + r.width)),
      bottom = Math.max(...rects.map((r) => r.y + r.height));
    await graph.zoomTo(
      Math.max(
        0.01,
        Math.min(
          1.5,
          safe.width / Math.max(1, right - left),
          safe.height / Math.max(1, bottom - top),
        ),
      ),
      false,
    );
    if (graph.destroyed) return;
    const center = graph.getViewportByCanvas([
      (left + right) / 2,
      (top + bottom) / 2,
    ]);
    await graph.translateBy(
      [
        safe.x + safe.width / 2 - center[0],
        safe.y + safe.height / 2 - center[1],
      ],
      false,
    );
  }
  const syncSelection = useEffectEvent(() => {
    const graph = instance.current;
    const host = container.current;
    if (!graph || !host) return;
    // Serialize G6 drawing; selecting/closing never recreates the graph or viewport.
    drawing.current = drawing.current
      .then(async () => {
        if (graph.destroyed) return;
        const rendered = styleGraph(
          toG6Data(
            data,
            host.clientWidth,
            host.clientHeight,
            selected ?? focusId,
            data.edges
              .filter((edge) => highlightedEdgeIds.includes(edge.id))
              .flatMap((edge) => [edge.source, edge.target]),
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
                    : '#b75b00',
                  strokeOpacity: 1,
                  lineWidth: connectionPath ? 2 : 4,
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
        const hiddenNodes = new Set(
          data.nodes
            .filter(
              (node) =>
                view.hidden.includes(node.kind) && !pathNodes.has(node.id),
            )
            .map((node) => node.id),
        );
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
                view.hidden.includes(
                  data.edges.find((item) => item.id === edge.id)!.relationType,
                ))
                ? 'hidden'
                : 'visible',
          },
        }));
        graph.setData(rendered);
        await graph.draw();
        const visibleCount =
          rendered.nodes?.filter((node) => node.style?.visibility !== 'hidden')
            .length ?? 0;
        minimapShown.current = visibleCount > 60 && host.clientWidth >= 768;
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
                      : (rendered.edges?.some(
                          (edge) =>
                            edge.id === id &&
                            edge.style?.visibility !== 'hidden',
                        ) ?? false),
                },
              ]
            : [],
        );
        if (graph.destroyed) return;
        renderedData.current = rendered;
        await syncVisualStates(graph, rendered);
        if (
          focusId &&
          focusId !== lastFocused.current &&
          rendered.nodes?.some((node) => node.id === focusId)
        )
          await graph.focusElement(focusId, false);
        lastFocused.current = focusId;
        if (fitPending.current) {
          fitPending.current = false;
          await fitVisibleGraph(graph);
        }
      })
      .catch(() => {
        if (!graph.destroyed) setRenderError(true);
      });
  });
  useEffect(() => {
    syncSelection();
  }, [
    selected,
    selectedEdgeId,
    focusId,
    focusHops,
    highlightedEdgeIds,
    connectionPath,
    view.hidden,
  ]);
  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let disposed = false;
    let graph: Graph | null = null;
    let observer: ResizeObserver | null = null;
    let resizeFrame: number | null = null;
    const clearHover = () => hoverNode(null);
    let pointerStart: { x: number; y: number } | null = null;
    const pointerDown = (event: PointerEvent) => {
      pointerStart = { x: event.clientX, y: event.clientY };
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
      }
    };
    const pointerUp = () => {
      pointerStart = null;
    };
    const stopFollowing = () => {
      followFit.current = false;
      centerTarget.current = null;
    };
    const viewportChanged = () => {
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
    const graphMode = data.metadata.mode;
    const rememberCamera = () => {
      if (!graph || disposed || graph.destroyed || instance.current !== graph)
        return;
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
        animation: false,
        data: styleGraph(
          toG6Data(data, host.clientWidth, host.clientHeight),
          appearance,
        ),
        behaviors: ['drag-canvas', 'zoom-canvas'],
        zoomRange: [0.01, 4],
        edge: {
          state: {
            related: {
              lineWidth: appearance.variant === 'improved' ? 2.5 : 2,
              stroke:
                appearance.variant === 'improved'
                  ? colors.selected
                  : themeColor('ink'),
              strokeOpacity: 1,
            },
            inactive: { strokeOpacity: 0.2 },
            selected: {
              lineWidth: appearance.variant === 'improved' ? 2.5 : 2,
              stroke:
                appearance.variant === 'improved'
                  ? colors.selected
                  : themeColor('ink'),
              strokeOpacity: 1,
            },
          },
        },
        node: {
          state: {
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
            },
          },
        },
      });
      graph.on('node:click', (event: IElementEvent) =>
        selectNode(event.target.id),
      );
      graph.on('node:pointerenter', (event: IElementEvent) =>
        hoverNode(event.target.id),
      );
      graph.on('node:pointerleave', (event: IElementEvent) =>
        leaveNode(event.target.id),
      );
      graph.on('canvas:pointerleave', () => hoverNode(null));
      graph.on('canvas:click', () => selectNode(null));
      graph.on('edge:click', (event: IElementEvent) =>
        selectEdge(event.target.id),
      );
      graph.on('aftertransform', () => {
        if (!graph || disposed) return;
        try {
          setZoom(graph.getZoom());
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
      const saved = readModeEntry(memoryOwner, graphMode)?.view.camera;
      // 창 크기가 달라졌으면 예전 위치가 화면 밖을 가리킬 수 있어 화면에 맞춰 연다.
      const camera =
        !appearance.preview &&
        saved &&
        sameViewport(saved.size, host.clientWidth, host.clientHeight)
          ? saved
          : null;
      followFit.current = !camera;
      fitPending.current = !camera;
      if (camera) {
        retainFocus();
        await graph.zoomTo(camera.zoom, false);
        await graph.translateTo(camera.position, false);
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
          graph.setSize(width, height);
          // 사이드바·패널이 열려 지도 크기가 바뀌면, 사이드바에서 고른 기업은 다시 가운데에
          // 두고, 그 밖에 사용자가 둔 위치는 화면 가운데를 유지한다.
          const target = centerTarget.current;
          if (
            target &&
            renderedData.current?.nodes?.some(
              (node) => String(node.id) === target,
            )
          )
            void graph.focusElement(target, false);
          else if (
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
  }, [data, retry, memoryOwner, appearance, colors.selected]);
  async function control(action: 'in' | 'out' | 'fit') {
    const graph = instance.current;
    if (!graph || graph.destroyed) return;
    try {
      if (action === 'fit') {
        followFit.current = true;
        await drawing.current;
        if (!graph.destroyed && instance.current === graph)
          await fitVisibleGraph(graph);
      } else {
        followFit.current = false;
        await graph.zoomTo(
          Math.max(
            0.01,
            Math.min(4, graph.getZoom() * (action === 'in' ? 1.2 : 1 / 1.2)),
          ),
          false,
        );
      }
    } catch {
      setRenderError(true);
    }
  }
  return (
    <div
      className="relationship-canvas [&_.graph-overview]:rounded-panel [&_.graph-overview]:border [&_.graph-overview]:border-panel-line [&_.graph-overview]:bg-zoop-paper [&_.graph-overview]:shadow-lg [&_.graph-overview]:bottom-16! [&_.graph-overview]:top-auto!"
      data-testid="graph-canvas"
    >
      <div
        ref={container}
        // G6 writes an inline position: relative on its container, which would size the host by
        // its own canvas. Keep it pinned to the map surface so each new graph measures full size.
        className="relationship-g6 absolute! inset-0"
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
          aria-label={`연결 없는 사건 ${stats.disconnected}건 보기`}
        >
          {stats.disconnected}
          <span className="block">연결 없는 사건</span>
        </button>
      )}
      <div className="relationship-source">
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
      <div className="relationship-zoom" aria-label="지도 확대 조절">
        <button onClick={() => void control('in')} aria-label="확대">
          <GraphIcon name="plus" />
        </button>
        <button onClick={() => void control('out')} aria-label="축소">
          <GraphIcon name="minus" />
        </button>
        <button
          onClick={() => void control('fit')}
          aria-label="전체 그래프 맞춤"
        >
          <GraphIcon name="fit" />
        </button>
        <output>{Math.round(zoom * 100)}% · 드래그로 이동 · 휠로 확대</output>
      </div>
      {selectedNode && (
        <p className="relationship-selection" role="status">
          {selectedNode.label}
          {selectedNode.geography
            ? ` · ${selectedNode.geography === 'domestic' ? '국내' : '국제'}`
            : ''}
          {selectedNode.holding ? ' · 보유' : ''}
          {selectedNode.watch ? ' · 관심' : ''}
        </p>
      )}
      {data.nodes.length === 0 && (
        <div className="relationship-message" role="status">
          {personal
            ? data.metadata.personalFilter === 'holdings'
              ? '보유종목이 없습니다.'
              : data.metadata.personalFilter === 'watchlist'
                ? '관심종목이 없습니다.'
                : '보유종목 또는 관심종목이 없습니다.'
            : '현재 표시할 수 있는 관계 데이터가 없습니다.'}
          {personal && <a href="/my">관심종목 설정</a>}
        </div>
      )}
      {data.nodes.length > 0 && data.edges.length === 0 && (
        <p className="relationship-empty-relations" role="status">
          현재 확인된 관련 관계가 없습니다.
        </p>
      )}
      {renderError && (
        <div className="relationship-message" role="alert">
          그래프를 표시하지 못했습니다.
          <button onClick={() => setRetry((v) => v + 1)}>다시 시도</button>
        </div>
      )}
      <div
        className="relationship-accessible-nodes"
        aria-label="키보드로 기업·사건·연결선 선택"
      >
        {data.nodes
          .filter((node) => !view.hidden.includes(node.kind))
          .map((node) => (
            <button
              key={node.id}
              aria-pressed={selected === node.id}
              onClick={() => onSelect?.(node.id)}
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
              aria-pressed={selectedEdgeId === edge.id}
              onClick={() => onSelectEdge?.(edge.id)}
            >
              연결선:{' '}
              {data.nodes.find((node) => node.id === edge.source)?.label} –{' '}
              {data.nodes.find((node) => node.id === edge.target)?.label} ·{' '}
              {edge.relationType === 'SHARES_ISSUE' ? '사건 공유' : '후속 관계'}
            </button>
          ))}
      </div>
    </div>
  );
}
