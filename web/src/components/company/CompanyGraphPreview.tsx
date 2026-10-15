import type { GraphResponse } from '@/types/map/graph';
export default function CompanyGraphPreview({
  data,
  highlighted = [],
  onSelect,
}: {
  data: GraphResponse;
  highlighted?: string[];
  onSelect?: (id: string, kind: 'company' | 'issue') => void;
}) {
  const points = new Map(
    data.nodes.map((node, i) => [
      node.id,
      {
        x: node.isFocus ? 160 : 160 + 110 * Math.cos(i * 2.4),
        y: node.isFocus ? 150 : 150 + 110 * Math.sin(i * 2.4),
      },
    ]),
  );
  return (
    <>
      <svg
        viewBox="0 0 320 300"
        role="img"
        aria-label="기준 시점 기업 관계 그래프"
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
                highlighted.includes(edge.id)
                  ? 'stroke-[#b75b00] stroke-[4px]'
                  : 'stroke-[#aaa] stroke-1'
              }

              strokeDasharray={edge.derived ? '4 4' : undefined}
            />
          ) : null;
        })}
        {data.nodes.map((node) => {
          const p = points.get(node.id)!;
          return (
            <g key={node.id}>
              <circle
                cx={p.x}
                cy={p.y}
                r={node.kind === 'company' ? 19 : 8}
                className={
                  node.kind === 'company'
                    ? 'fill-white stroke-[#333]'
                    : 'fill-[#333] stroke-[#333]'
                }
              />
              <text
                x={p.x}
                y={p.y + 31}
                textAnchor="middle"
                className="text-[10px]"
              >
                {node.label.slice(0, 15)}
              </text>
            </g>
          );
        })}
      </svg>
      <ul className="max-h-60 overflow-auto">
        {data.nodes.map((node) => (
          <li key={node.id}>
            <button onClick={() => onSelect?.(node.id, node.kind)}>
              {node.kind === 'company' ? '기업' : '사건'} · {node.label}
            </button>
          </li>
        ))}
      </ul>
      {!data.nodes.length && (
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
