import { useEffect, useEffectEvent, useRef, useState } from 'react';
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
}: {
  data: GraphResponse;
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
}) {
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
      const active =
        hovered.current &&
        visibleIds.has(hovered.current) &&
        (!focusId || focusedNodes.has(hovered.current))
          ? hovered.current
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
                ? 'hovered'
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
  const syncSelection = useEffectEvent(() => {
    const graph = instance.current;
    const host = container.current;
    if (!graph || !host) return;
    // Serialize G6 drawing; selecting/closing never recreates the graph or viewport.
    drawing.current = drawing.current
      .then(async () => {
        if (graph.destroyed) return;
        const rendered = toG6Data(
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
        );
        rendered.edges = rendered.edges?.map((edge) =>
          highlightedEdgeIds.includes(String(edge.id))
            ? {
                ...edge,
                style: {
                  ...edge.style,
                  stroke: connectionPath ? '#1a1a1a' : '#b75b00',
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
              fill: '#dfdfdc',
              stroke: '#1a1a1a',
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
        graph.setPlugins(
          visibleCount > 60 && host.clientWidth >= 768
            ? [
                {
                  type: 'minimap',
                  key: 'graph-overview',
                  size: [192, 128],
                  position: 'right-bottom',
                  className:
                    'hidden md:block rounded-panel border border-panel-line bg-white shadow-lg',
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
    host.addEventListener('pointerleave', clearHover);
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
        data: toG6Data(data, host.clientWidth, host.clientHeight),
        behaviors: ['drag-canvas', 'zoom-canvas'],
        zoomRange: [0.25, 4],
        edge: {
          state: {
            related: { lineWidth: 2, stroke: '#1a1a1a', strokeOpacity: 1 },
            inactive: { strokeOpacity: 0.2 },
            selected: { lineWidth: 2, stroke: '#1a1a1a', strokeOpacity: 1 },
          },
        },
        node: {
          state: {
            related: { opacity: 1, lineWidth: 1.4, labelFill: '#1a1a1a' },
            inactive: { opacity: 0.35 },
            hovered: {
              opacity: 1,
              lineWidth: 2,
              halo: true,
              haloStroke: '#1a1a1a',
              haloFill: 'transparent',
              labelFill: '#1a1a1a',
            },
            selected: {
              lineWidth: 2,
              halo: true,
              haloStroke: '#1a1a1a',
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
      const camera = readModeEntry(memoryOwner, graphMode)?.view.camera;
      // 창 크기가 달라졌으면 예전 위치가 화면 밖을 가리킬 수 있어 기본 배치로 연다.
      if (
        camera &&
        sameViewport(camera.size, host.clientWidth, host.clientHeight)
      ) {
        retainFocus();
        await graph.zoomTo(camera.zoom, false);
        await graph.translateTo(camera.position, false);
      }
      instance.current = graph;
      syncSelection();
      observer = new ResizeObserver(() => {
        if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => {
          resizeFrame = null;
          if (!graph || disposed || graph.destroyed) return;
          if (host.clientWidth <= 0 || host.clientHeight <= 0) return;
          graph.setSize(host.clientWidth, host.clientHeight);
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
      observer?.disconnect();
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      graph?.destroy();
      instance.current = null;
    };
  }, [data, retry, memoryOwner]);
  async function control(action: 'in' | 'out' | 'fit') {
    const graph = instance.current;
    if (!graph || graph.destroyed) return;
    try {
      if (action === 'fit') await graph.fitView({ when: 'always' }, false);
      else
        await graph.zoomTo(
          Math.max(
            0.25,
            Math.min(4, graph.getZoom() * (action === 'in' ? 1.2 : 1 / 1.2)),
          ),
          false,
        );
    } catch {
      setRenderError(true);
    }
  }
  return (
    <div className="relationship-canvas" data-testid="graph-canvas">
      <div
        ref={container}
        // G6 writes an inline position: relative on its container, which would size the host by
        // its own canvas. Keep it pinned to the map surface so each new graph measures full size.
        className="relationship-g6 absolute! inset-0"
        role="img"
        aria-label={`${personal ? '내 종목' : '시장 전체'} 관계 지도: 기업 ${stats.company}개, 사건 ${stats.issue}개. 드래그로 이동하고 휠로 확대합니다.`}
      />
      {!focusId && (
        <aside
          className="relationship-legend z-10 bg-zoop-map/60 pb-3"
          aria-label="그래프 범례"
        >
          <div className="relationship-title">
            <h1>{personal ? '내 종목 지도' : '시장 전체 지도'}</h1>
          </div>
          <p className="relationship-subtitle">
            (RELATIONSHIP MAP) · 기업·사건 관계
          </p>
          <p className="relationship-meta">
            {stats.company} COMPANIES · {stats.sharedIssues} SHARED EVENTS
          </p>
          <div className="mt-3 border-t border-zoop-line pt-2">
            <h2 className="mb-2 text-[10px] tracking-widest">
              LEGEND · 표시 필터
            </h2>
            <div className="grid grid-cols-2 gap-1">
              {(
                [
                  ['company', '기업'],
                  ['issue', '사건'],
                  ['INVOLVES', '직접 관련'],
                  ['STRUCTURALLY_RELATED_TO', '구조적 관련'],
                  ['FOLLOWS', '후속 사건'],
                  ['SHARES_ISSUE', '사건 공유'],
                ] as [LegendKey, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className="pointer-events-auto rounded border border-zoop-line px-1 py-1 text-left text-[10px] aria-pressed:bg-white aria-pressed:font-bold focus-visible:outline-2"
                  aria-pressed={!view.hidden.includes(key)}
                  disabled={
                    (key === 'company' || key === 'issue') &&
                    !view.hidden.includes(key) &&
                    view.hidden.includes(
                      key === 'company' ? 'issue' : 'company',
                    )
                  }
                  onClick={() => toggleKind(key)}
                >
                  {view.hidden.includes(key) ? '□' : '■'} {label}{' '}
                  {key === 'company'
                    ? stats.company
                    : key === 'issue'
                      ? stats.issue
                      : data.edges.filter((edge) => edge.relationType === key)
                          .length}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[10px]">○ 기업 · ◆ 사건 · 크기=활동</p>
          </div>
        </aside>
      )}
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
