import { useRef, useState, type PointerEvent } from 'react';
import type { GraphResponse } from '@/types/map/graph';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';

export default function CompanyGraphPreview({
  data,
  highlighted = [],
  selectedId,
  onSelect,
}: {
  data: GraphResponse;
  highlighted?: string[];
  selectedId?: string | null;
  onSelect?: (id: string, kind: 'company' | 'issue') => void;
}) {
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const drag = useRef<{
    x: number;
    y: number;
    viewX: number;
    viewY: number;
    moved: boolean;
    pointerId: number;
  } | null>(null);
  const wasDragged = useRef(false);
  const points = new Map(
    data.nodes.map((node, i) => [
      node.id,
      {
        x: node.isFocus ? 160 : 160 + 110 * Math.cos(i * 2.4),
        y: node.isFocus ? 150 : 150 + 110 * Math.sin(i * 2.4),
      },
    ]),
  );
  function zoom(factor: number) {
    setView((old) => {
      const scale = Math.min(4, Math.max(0.5, old.scale * factor));
      return {
        scale,
        x: old.x + (320 / old.scale - 320 / scale) / 2,
        y: old.y + (300 / old.scale - 300 / scale) / 2,
      };
    });
  }
  function down(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0 || drag.current) return;
    wasDragged.current = false;
    if ((event.target as Element).closest('g')) return;
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      viewX: view.x,
      viewY: view.y,
      moved: false,
      pointerId: event.pointerId,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<SVGSVGElement>) {
    const origin = drag.current;
    if (!origin || event.pointerId !== origin.pointerId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    origin.moved ||=
      Math.abs(event.clientX - origin.x) + Math.abs(event.clientY - origin.y) >
      4;
    wasDragged.current = origin.moved;
    setView({
      scale: view.scale,
      x:
        origin.viewX -
        ((event.clientX - origin.x) * 320) / rect.width / view.scale,
      y:
        origin.viewY -
        ((event.clientY - origin.y) * 300) / rect.height / view.scale,
    });
  }
  return (
    <>
      <p>
        기업 {data.nodes.filter((n) => n.kind === 'company').length} · 사건{' '}
        {data.nodes.filter((n) => n.kind === 'issue').length} · 연결{' '}
        {data.edges.length}
      </p>
      <p>○ 기업 · ◆ 사건 · 점선은 파생 관계입니다.</p>
      <svg
        viewBox={`${view.x} ${view.y} ${320 / view.scale} ${300 / view.scale}`}
        role="img"
        aria-label="기준 시점 기업 관계 그래프"
        className="h-auto w-full touch-none rounded-[3px] bg-zoop-line"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={(event) => {
          if (drag.current?.pointerId === event.pointerId) drag.current = null;
        }}
        onPointerCancel={(event) => {
          if (drag.current?.pointerId === event.pointerId) drag.current = null;
        }}
        onLostPointerCapture={() => {
          drag.current = null;
        }}
      >
        {data.edges.map((edge) => {
          const a = points.get(edge.source),
            b = points.get(edge.target);
          return a && b ? (
            <line
              key={edge.id}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className={
                highlighted.includes(edge.id) &&
                !edge.derived &&
                edge.assertionStatus === 'confirmed'
                  ? 'stroke-[#b75b00] stroke-[4px]'
                  : 'stroke-zoop-faint stroke-1'
              }
              strokeDasharray={edge.derived ? '4 4' : undefined}
            >
              <title>{edge.summary}</title>
            </line>
          ) : null;
        })}
        {data.nodes.map((node) => {
          const point = points.get(node.id)!;
          const selected = selectedId === node.id;
          return (
            <g
              key={node.id}
              className="cursor-pointer"
              onClick={() => {
                if (!wasDragged.current) onSelect?.(node.id, node.kind);
              }}
            >
              <title>{node.label}</title>
              {node.kind === 'company' ? (
                <circle
                  cx={point.x}
                  cy={point.y}
                  r={19}
                  className={
                    selected
                      ? 'fill-white stroke-zoop-ink stroke-[3px]'
                      : 'fill-white stroke-zoop-muted stroke-1'
                  }
                />
              ) : (
                <polygon
                  points={`${point.x},${point.y - 9} ${point.x + 9},${point.y} ${point.x},${point.y + 9} ${point.x - 9},${point.y}`}
                  className={
                    selected
                      ? 'fill-zoop-ink stroke-white stroke-2'
                      : 'fill-zoop-muted'
                  }
                />
              )}
              <text
                x={point.x}
                y={point.y + 31}
                textAnchor="middle"
                className="fill-zoop-ink text-[10px]"
              >
                {node.label.slice(0, 15)}
              </text>
            </g>
          );
        })}
      </svg>
      <nav aria-label="기업 관계 그래프 화면 조절">
        <button
          type="button"
          aria-label="기업 관계 그래프 확대"
          className={ui.button}
          disabled={view.scale >= 4}
          onClick={() => zoom(1.25)}
        >
          +
        </button>
        <button
          type="button"
          aria-label="기업 관계 그래프 축소"
          className={ui.button}
          disabled={view.scale <= 0.5}
          onClick={() => zoom(0.8)}
        >
          −
        </button>
        <button
          type="button"
          className={ui.button}
          onClick={() => setView({ x: 0, y: 0, scale: 1 })}
        >
          기업 관계 그래프 전체 보기
        </button>
      </nav>
      <p role="status">
        확대 비율 {Math.round(view.scale * 100)}% · 드래그로 이동하거나 아래
        목록에서 선택할 수 있어요.
      </p>
      <ul
        className="max-h-60 overflow-auto"
        aria-label="기업 관계 그래프 노드 목록"
      >
        {data.nodes.map((node) => (
          <li key={node.id}>
            <button
              type="button"
              aria-pressed={selectedId === node.id}
              className={ui.button}
              onClick={() => onSelect?.(node.id, node.kind)}
            >
              {node.kind === 'company' ? '기업' : '사건'} · {node.label}
            </button>
          </li>
        ))}
      </ul>
      {data.edges.length === 0 && (
        <p>
          관계 없음 · {data.metadata.emptyReason ?? '확인된 관계가 없습니다.'}
        </p>
      )}
      {data.metadata.partial && (
        <p role="alert">
          일부 관계 자료를 받지 못했어요. 전체 관계로 해석하지 마세요.
        </p>
      )}
      {data.metadata.truncated && (
        <p>표시 상한에 따라 일부 관계가 생략되었습니다.</p>
      )}
    </>
  );
}
