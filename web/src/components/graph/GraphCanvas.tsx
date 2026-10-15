import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { Graph, type IElementEvent } from '@antv/g6';
import type { GraphResponse } from '@/types/map/graph';
import { isSelectableRelation } from '@/types/map/relation';
import GraphIcon from './GraphIcon';
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
}: {
  data: GraphResponse;
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  focusId?: string | null;
  focusHops?: 1 | 2;
  highlightedEdgeIds?: string[];
  selectedEdgeId?: string | null;
  onSelectEdge?: (id: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<Graph | null>(null);
  const [zoom, setZoom] = useState(1);
  const drawing = useRef(Promise.resolve());
  const lastFocused = useRef<string | null>(null);
  const selectNode = useEffectEvent((id: string | null) => onSelect?.(id));
  const selectEdge = useEffectEvent((id: string) => {
    if (data.edges.some((edge) => edge.id === id && isSelectableRelation(edge)))
      onSelectEdge?.(id);
  });
  const [renderError, setRenderError] = useState(false);
  const [retry, setRetry] = useState(0);
  const stats = graphSummary(data);
  const personal = data.metadata.mode === 'personal';
  const focusedNodes = focusNeighborhood(data, focusId, focusHops);
  const center =
    data.nodes.find((n) => n.id === selected && n.kind === 'company') ??
    data.nodes.find((n) => n.isFocus);
  const selectedNode = data.nodes.find((n) => n.id === selected);
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
          focusedNodes,
        );
        rendered.edges = rendered.edges?.map((edge) =>
          highlightedEdgeIds.includes(String(edge.id))
            ? {
                ...edge,
                style: { ...edge.style, stroke: '#b75b00', lineWidth: 4 },
              }
            : edge,
        );
        graph.setData(rendered);
        await graph.draw();
        if (graph.destroyed) return;
        await graph.setElementState(
          Object.fromEntries(
            [...(rendered.nodes ?? []), ...(rendered.edges ?? [])].map(
              (node) => [
                node.id,
                node.id === selected || node.id === selectedEdgeId
                  ? ['selected']
                  : [],
              ],
            ),
          ),
        );
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
  }, [selected, selectedEdgeId, focusId, focusHops, highlightedEdgeIds]);
  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let disposed = false;
    let graph: Graph | null = null;
    let observer: ResizeObserver | null = null;
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
            selected: { lineWidth: 2, stroke: '#1a1a1a', strokeOpacity: 1 },
          },
        },
        node: {
          state: {
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
      graph.on('canvas:click', () => selectNode(null));
      graph.on('edge:click', (event: IElementEvent) =>
        selectEdge(event.target.id),
      );
      graph.on('aftertransform', () => {
        if (!graph || disposed) return;
        try {
          setZoom(graph.getZoom());
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
      instance.current = graph;
      syncSelection();
      observer = new ResizeObserver(() => {
        if (graph && !disposed)
          graph.setSize(host.clientWidth, host.clientHeight);
      });
      observer.observe(host);
    }
    void mount().catch(() => {
      if (!disposed) setRenderError(true);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      graph?.destroy();
      instance.current = null;
    };
  }, [data, retry]);
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
        className="relationship-g6"
        role="img"
        aria-label={`${personal ? '내 종목' : '시장 전체'} 관계 지도: 기업 ${stats.company}개, 사건 ${stats.issue}개. 드래그로 이동하고 휠로 확대합니다.`}
      />
      {!focusId && (
        <aside className="relationship-legend" aria-label="그래프 범례">
          <div className="relationship-title">
            <i>(01)</i>
            <h1>{center?.label ?? '관계 지도'}</h1>
          </div>
          <p className="relationship-subtitle">
            (RELATIONSHIP MAP) · 중심 관계
          </p>
          <p className="relationship-meta">
            {stats.company} COMPANIES · {stats.sharedIssues} SHARED EVENTS
          </p>
          <div className="relationship-legend-items">
            <h2>LEGEND</h2>
            <span>
              <b className="legend-company" />
              기업
            </span>
            <span>
              <b className="legend-focus" />
              중심·선택
            </span>
            <span>
              <b className="legend-issue" />
              공유 사건
            </span>
            <span>
              <b className="legend-folded">ϟn</b>접힌 사건
            </span>
            <span>
              <b className="legend-line" />
              직접 관련
            </span>
            <span>
              <b className="legend-line dashed" />
              사건 공유
            </span>
            <span>
              <b className="legend-line arrow" />
              후속 사건
            </span>
            <span>
              <b className="legend-size">○◯</b>크기=활동
            </span>
          </div>
        </aside>
      )}
      <div className="relationship-disconnected">
        <span>{stats.disconnected}</span>
        <p>연결 없는 사건</p>
      </div>
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
        <output>
          {Math.round(zoom * (personal ? 69 : 100))}% · 드래그로 이동 · 휠로
          확대
        </output>
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
        {data.nodes.map((node) => (
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
        {data.edges.filter(isSelectableRelation).map((edge) => (
          <button
            key={edge.id}
            aria-pressed={selectedEdgeId === edge.id}
            onClick={() => onSelectEdge?.(edge.id)}
          >
            연결선: {data.nodes.find((node) => node.id === edge.source)?.label}{' '}
            – {data.nodes.find((node) => node.id === edge.target)?.label} ·{' '}
            {edge.relationType === 'SHARES_ISSUE' ? '사건 공유' : '후속 관계'}
          </button>
        ))}
      </div>
    </div>
  );
}
