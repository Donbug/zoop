import type { GraphData } from '@antv/g6';
import type { GraphResponse } from '@/types/map/graph';

export type Positions = Record<string, [number, number]>;

// D-GRP-01/01b/07b · coordinate memories never cross owners, snapshots or arrangements.
export function positionKey(
  owner: string,
  data: GraphResponse,
  arrangement: string,
) {
  const m = data.metadata;
  return `zoop.graph.positions:${JSON.stringify([owner, m.mode, m.personalFilter, m.graphVersion ?? m.asOf, arrangement])}`;
}
export function readPositions(key: string): Positions {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(key) ?? '{}');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter(
        ([, point]) =>
          Array.isArray(point) &&
          point.length === 2 &&
          point.every((n) => typeof n === 'number' && Number.isFinite(n)),
      ),
    );
  } catch {
    return {};
  }
}
export function savePositions(
  key: string,
  nodes: NonNullable<GraphData['nodes']>,
  width: number,
  height: number,
  graphNodeIds: ReadonlySet<string>,
) {
  // A rendered subset omits folded issues. Retain those coordinates while the
  // full response still contains them, and prune nodes removed from this snapshot.
  const retained = Object.fromEntries(
    Object.entries(readPositions(key)).filter(([id]) => graphNodeIds.has(id)),
  );
  const updated = Object.fromEntries(
    nodes
      .filter(
        (n) =>
          n.id !== '__isolated__' &&
          graphNodeIds.has(String(n.id)) &&
          Number.isFinite(n.style?.x) &&
          Number.isFinite(n.style?.y),
      )
      .map((n) => [
        n.id,
        [Number(n.style?.x) - width / 2, Number(n.style?.y) - height / 2],
      ]),
  );
  try {
    sessionStorage.setItem(key, JSON.stringify({ ...retained, ...updated }));
  } catch {
    /* Disabled/quota-limited storage must not break map input. */
  }
}
export function restorePositions(
  base: GraphData,
  saved: Positions,
  width: number,
  height: number,
): GraphData {
  const nodes = base.nodes ?? [];
  const existing = new Map(
    nodes
      .filter((n) => Object.hasOwn(saved, String(n.id)))
      .map((n) => [
        String(n.id),
        {
          x: saved[String(n.id)][0] + width / 2,
          y: saved[String(n.id)][1] + height / 2,
        },
      ]),
  );
  if (!existing.size) return base;
  const placed = [...existing.values()];
  return {
    ...base,
    nodes: nodes.map((node, index) => {
      const id = String(node.id);
      let point = existing.get(id);
      if (!point) {
        const link = base.edges?.find(
          (e) =>
            (e.source === id && existing.has(String(e.target))) ||
            (e.target === id && existing.has(String(e.source))),
        );
        const neighbor = link
          ? existing.get(String(link.source === id ? link.target : link.source))
          : undefined;
        point = neighbor
          ? {
              x: neighbor.x + Math.cos(index * 2.4) * 180,
              y: neighbor.y + Math.sin(index * 2.4) * 180,
            }
          : { x: Number(node.style?.x ?? 0), y: Number(node.style?.y ?? 0) };
        for (
          let step = 0;
          step < 80 &&
          placed.some((p) => Math.hypot(p.x - point!.x, p.y - point!.y) < 130);
          step++
        ) {
          const radius = 180 + step * 12;
          point = {
            x:
              (neighbor?.x ?? Number(node.style?.x ?? 0)) +
              Math.cos(step * 2.4) * radius,
            y:
              (neighbor?.y ?? Number(node.style?.y ?? 0)) +
              Math.sin(step * 2.4) * radius,
          };
        }
        placed.push(point);
      }
      return { ...node, style: { ...node.style, ...point } };
    }),
  };
}
