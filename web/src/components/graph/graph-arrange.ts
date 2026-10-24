import type { GraphData } from '@antv/g6';
import type { GraphResponse } from '@/types/map/graph';

// D-GRP-07b 포커스 모드와 D-GRP-01 [흐름 순으로 정렬]의 노드 배치(docs/design/design-direction.md).
// 화면 표시용 좌표만 바꾼다. 데이터·선택·연결은 바꾸지 않고, 모드를 끄면 원래 지도 배치로 돌아간다.

type Node = NonNullable<GraphData['nodes']>[number];
type Point = { x: number; y: number };

const ISOLATED = '__isolated__';
const xy = (node: Node): Point => ({
  x: Number(node.style?.x ?? 0),
  y: Number(node.style?.y ?? 0),
});
/** 노드의 세로 반지름과 위·아래 이름표 높이(스타일 반영 후 크기 기준). size는 숫자 또는 [너비, 높이]다. */
function verticalExtent(node: Node) {
  const size = node.style?.size;
  const height = Array.isArray(size)
    ? Number(size[1] ?? size[0] ?? 20)
    : Number(size ?? 20);
  const label = node.style?.labelText
    ? Number(node.style?.labelFontSize ?? 12) * 1.4 +
      Math.abs(Number(node.style?.labelOffsetY ?? 0))
    : 0;
  const top = node.style?.labelPlacement === 'top';
  return {
    radius: (Number.isFinite(height) ? height : 20) / 2,
    above: top ? label : 0,
    below: top ? 0 : label,
  };
}
/** 노드 사이 최소 여백 */
const NODE_GAP = 12;
const place = (node: Node, point: Point): Node => ({
  ...node,
  style: { ...node.style, x: point.x, y: point.y },
});

/** 포커스 노드에서 각 노드까지의 단계(1 또는 2). 포커스 노드는 0 */
export function focusRings(
  data: GraphResponse,
  focusId: string,
  hops: 1 | 2,
): Map<string, number> {
  const rings = new Map([[focusId, 0]]);
  let frontier = new Set([focusId]);
  for (let depth = 1; depth <= hops; depth += 1) {
    const next = new Set<string>();
    for (const edge of data.edges) {
      if (frontier.has(edge.source) && !rings.has(edge.target))
        next.add(edge.target);
      if (frontier.has(edge.target) && !rings.has(edge.source))
        next.add(edge.source);
    }
    next.forEach((id) => rings.set(id, depth));
    frontier = next;
  }
  return rings;
}

/**
 * 포커스 모드: 포커스 노드를 가운데, 1단계 이웃을 첫 링, 2단계 이웃을 둘째 링에 둔다.
 * 링 안 순서는 원래 지도에서 포커스 노드를 기준으로 한 방향을 따른다. 나머지 노드는 숨긴다.
 */
export function arrangeFocus(
  rendered: GraphData,
  data: GraphResponse,
  focusId: string,
  hops: 1 | 2,
  width: number,
  height: number,
): { nodes: Node[]; hidden: Set<string> } {
  const nodes = rendered.nodes ?? [];
  const focus = nodes.find((node) => node.id === focusId);
  if (!focus) return { nodes, hidden: new Set() };
  const rings = focusRings(data, focusId, hops);
  const origin = xy(focus);
  const center = { x: width / 2, y: height / 2 };
  const base = Math.min(width, height);
  const ringOf = (level: number) =>
    nodes
      .filter((node) => rings.get(String(node.id)) === level)
      .map((node) => {
        const p = xy(node);
        return {
          id: String(node.id),
          angle: Math.atan2(p.y - origin.y, p.x - origin.x),
        };
      })
      .sort((a, b) => a.angle - b.angle || a.id.localeCompare(b.id));
  const first = ringOf(1);
  const second = ringOf(2);
  // 링 둘레가 노드 사이 최소 간격을 넘도록 반지름을 정한다.
  const r1 = Math.max(base * 0.28, (first.length * 90) / (2 * Math.PI));
  const r2 = Math.max(r1 + base * 0.2, (second.length * 70) / (2 * Math.PI));
  const targets = new Map<string, Point>([[focusId, center]]);
  for (const [ring, radius] of [
    [first, r1],
    [second, r2],
  ] as const) {
    const start = ring[0]?.angle ?? 0;
    ring.forEach((item, index) => {
      const angle = start + (index * 2 * Math.PI) / ring.length;
      targets.set(item.id, {
        x: center.x + Math.cos(angle) * radius,
        y: center.y + Math.sin(angle) * radius,
      });
    });
  }
  const hidden = new Set<string>();
  const arranged = nodes.map((node) => {
    const target = targets.get(String(node.id));
    if (target) return place(node, target);
    hidden.add(String(node.id));
    return node;
  });
  return { nodes: arranged, hidden };
}

/**
 * [흐름 순으로 정렬]: 사건 → 관련 기업, 선행 사건 → 후속 사건(FOLLOWS) 방향으로 왼쪽에서 오른쪽으로 층을 나눈다.
 * 같은 층 안에서는 앞 층 연결의 평균 위치를 따라 정렬해 교차를 줄인다. 방향 연결이 없는 노드는 맨 오른쪽 층에 둔다.
 */
export function arrangeFlow(
  rendered: GraphData,
  data: GraphResponse,
  width: number,
  height: number,
): Node[] {
  const nodes = rendered.nodes ?? [];
  const ids = nodes
    .map((node) => String(node.id))
    .filter((id) => id !== ISOLATED);
  const present = new Set(ids);
  const kind = new Map(data.nodes.map((node) => [node.id, node.kind]));
  const next = new Map(ids.map((id) => [id, [] as string[]]));
  const previous = new Map(ids.map((id) => [id, [] as string[]]));
  const directed = new Set<string>();
  for (const edge of data.edges) {
    if (!present.has(edge.source) || !present.has(edge.target)) continue;
    let from: string | null = null;
    let to: string | null = null;
    if (edge.relationType === 'FOLLOWS') {
      // 공개 계약은 뒤 사건(source) → 앞 사건(target)으로 저장한다.
      // 화면의 시간 흐름은 앞 사건 → 뒤 사건이므로 배치 방향만 뒤집는다.
      from = edge.target;
      to = edge.source;
    } else if (
      edge.relationType === 'INVOLVES' ||
      edge.relationType === 'STRUCTURALLY_RELATED_TO'
    ) {
      from = kind.get(edge.source) === 'issue' ? edge.source : edge.target;
      to = from === edge.source ? edge.target : edge.source;
    }
    if (!from || !to || from === to) continue;
    next.get(from)!.push(to);
    previous.get(to)!.push(from);
    directed.add(from).add(to);
  }
  // 가장 긴 경로로 층을 정한다. 순환(드묾)은 남은 노드를 현재 층에 두어 끊는다.
  const rank = new Map<string, number>();
  const indegree = new Map(ids.map((id) => [id, previous.get(id)!.length]));
  let queue = ids.filter((id) => directed.has(id) && indegree.get(id) === 0);
  queue.forEach((id) => rank.set(id, 0));
  while (queue.length) {
    const following: string[] = [];
    for (const id of queue)
      for (const target of next.get(id)!) {
        rank.set(target, Math.max(rank.get(target) ?? 0, rank.get(id)! + 1));
        indegree.set(target, indegree.get(target)! - 1);
        if (indegree.get(target) === 0) following.push(target);
      }
    queue = following;
  }
  for (const id of ids)
    if (directed.has(id) && !rank.has(id))
      rank.set(
        id,
        Math.max(0, ...previous.get(id)!.map((p) => rank.get(p) ?? 0)),
      );
  const last = directed.size ? Math.max(0, ...rank.values()) : -1;
  const original = new Map(nodes.map((node) => [String(node.id), xy(node)]));
  const extent = new Map(
    nodes.map((node) => [String(node.id), verticalExtent(node)]),
  );
  /** 한 열의 노드를 위에서부터 쌓은 y. 기본 간격과 이웃한 두 노드의 실제 크기·이름표 중 큰 쪽을 쓴다. */
  const stack = (members: string[], baseGap: number) => {
    const offsets = [0];
    for (let index = 1; index < members.length; index += 1) {
      const upper = extent.get(members[index - 1])!;
      const lower = extent.get(members[index])!;
      const need =
        upper.radius + upper.below + lower.above + lower.radius + NODE_GAP;
      offsets.push(offsets[index - 1] + Math.max(baseGap, need));
    }
    const total = offsets.at(-1) ?? 0;
    return offsets.map((offset) => height / 2 - total / 2 + offset);
  };
  const order = new Map<string, number>();
  const targets = new Map<string, Point>();
  const margin = 80;
  const rowGapOf = (count: number) =>
    Math.min(120, Math.max(88, (height - margin * 2) / Math.max(1, count - 1)));
  const columnsOf = new Map<number, string[]>();
  for (const id of ids)
    if (rank.has(id))
      columnsOf.set(rank.get(id)!, [
        ...(columnsOf.get(rank.get(id)!) ?? []),
        id,
      ]);
  // 방향 연결이 없는 노드(사건과 이어지지 않은 기업 등)는 한 줄로 길게 두지 않고 여러 열로 나눈다.
  const loose = ids
    .filter((id) => !directed.has(id))
    .sort(
      (a, b) =>
        original.get(a)!.y - original.get(b)!.y ||
        original.get(a)!.x - original.get(b)!.x ||
        a.localeCompare(b),
    );
  const tallest = Math.max(0, ...[...columnsOf.values()].map((c) => c.length));
  const rows = Math.min(8, Math.max(4, tallest));
  const looseColumns = Math.ceil(loose.length / rows);
  const columns = last + 1 + looseColumns;
  const colGap = Math.max(180, (width - margin * 2) / Math.max(1, columns - 1));
  for (let column = 0; column <= last; column += 1) {
    const members = (columnsOf.get(column) ?? [])
      .map((id) => {
        const parents = previous.get(id)!.filter((p) => order.has(p));
        const barycenter = parents.length
          ? parents.reduce((sum, p) => sum + order.get(p)!, 0) / parents.length
          : Number.POSITIVE_INFINITY;
        return { id, barycenter, y: original.get(id)!.y };
      })
      .sort(
        (a, b) =>
          a.barycenter - b.barycenter || a.y - b.y || a.id.localeCompare(b.id),
      );
    const ys = stack(
      members.map((member) => member.id),
      rowGapOf(members.length),
    );
    members.forEach((member, index) => {
      order.set(member.id, index);
      targets.set(member.id, {
        x: margin + column * colGap,
        y: ys[index],
      });
    });
  }
  for (let start = 0; start < loose.length; start += rows) {
    const members = loose.slice(start, start + rows);
    const ys = stack(members, rowGapOf(rows));
    const column = last + 1 + start / rows;
    members.forEach((id, index) =>
      targets.set(id, { x: margin + column * colGap, y: ys[index] }),
    );
  }
  return nodes.map((node) => {
    const target = targets.get(String(node.id));
    return target ? place(node, target) : node;
  });
}
