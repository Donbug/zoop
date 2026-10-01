// EdgeGlyph: 연결선의 성격을 선 모양 견본으로 보여준다(범례 칩·연결 목록 앞 표지). 글자 태그는 두지 않는다.
// 그래프(graph-canvas)와 같은 규칙: 직접=2px 실선, 구조=2px 파선, 후속=1.5px 실선, 사건 공유=1.5px 점선.
// 방향이 있는 관계(사건 공유 제외)는 화살촉을 붙인다.
import type { RelationType } from "@/lib/labels";
import { cn } from "@/lib/utils";

const edgeColor: Record<RelationType, string> = {
  INVOLVES: "var(--color-graph-edge-involves)",
  STRUCTURALLY_RELATED_TO: "var(--color-graph-edge-structurally-related)",
  FOLLOWS: "var(--color-graph-edge-follows)",
  SHARES_ISSUE: "var(--color-graph-edge-shares-issue)",
};
const edgeDash: Record<RelationType, string | undefined> = {
  INVOLVES: undefined,
  STRUCTURALLY_RELATED_TO: "6 3",
  FOLLOWS: undefined,
  SHARES_ISSUE: "2 3",
};
const edgeWidth: Record<RelationType, number> = { INVOLVES: 2, STRUCTURALLY_RELATED_TO: 2, FOLLOWS: 1.5, SHARES_ISSUE: 1.5 };

export function EdgeGlyph({ type, className }: { type: RelationType; className?: string }) {
  const color = edgeColor[type];
  const arrow = type !== "SHARES_ISSUE";
  return (
    <svg viewBox="0 0 28 10" className={cn("h-2.5 w-7 shrink-0", className)} aria-hidden="true">
      <line x1="1" y1="5" x2={arrow ? 21 : 27} y2="5" stroke={color} strokeWidth={edgeWidth[type]} strokeDasharray={edgeDash[type]} />
      {arrow && <path d="M21 1.5 L27 5 L21 8.5 Z" fill={color} />}
    </svg>
  );
}
