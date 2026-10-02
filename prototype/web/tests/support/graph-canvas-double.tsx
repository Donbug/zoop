// 지도 캔버스 대역. 실제 GraphCanvas는 Cytoscape로 그리는데 jsdom에는 그릴 화면이 없다(배치·카메라도 시험 대상이 아니다).
// 이 대역은 캔버스가 받은 노드를 버튼 목록으로 내보내고, 누르면 실제 캔버스처럼 onSelect를 부른다.
// 그래서 시험은 "지도에 어떤 노드가 있는가"와 "고른 노드가 무엇인가"만 본다.
import type { Schemas } from "@/api/client";

interface Props {
  nodes: Schemas["GraphNode"][];
  selection: { kind: "node" | "edge"; id: string } | null;
  onSelect: (selection: { kind: "node" | "edge"; id: string } | null) => void;
  ariaLabel: string;
}

export function GraphCanvas({ nodes, selection, onSelect, ariaLabel }: Props) {
  return (
    <div role="group" aria-label={ariaLabel}>
      <ul aria-label="지도의 노드">
        {nodes.map((node) => (
          <li key={node.id}>
            <button type="button" aria-pressed={selection?.kind === "node" && selection.id === node.id} onClick={() => onSelect({ kind: "node", id: node.id })}>
              {node.label}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
