import type { GraphResponse } from '@/types/map/graph';

type Point = { x: number; y: number };
const cache = new WeakMap<GraphResponse, Map<string, Point>>();

// D-GRP-01/01b: translate whole disconnected groups, never scale their interior.
// Bounds include folded issues so expanding one does not move neighboring groups.
export function compactRelationshipGroups(
  points: Map<string, Point>,
  groups: string[][],
) {
  if (groups.length < 2) return;
  const gap = 360;
  const boxes = groups
    .map((ids) => {
      const members = ids.map((id) => points.get(id)!);
      const minX = Math.min(...members.map((p) => p.x));
      const minY = Math.min(...members.map((p) => p.y));
      const width = Math.max(120, Math.max(...members.map((p) => p.x)) - minX);
      const height = Math.max(120, Math.max(...members.map((p) => p.y)) - minY);
      return { ids, minX, minY, width, height };
    })
    .sort(
      (a, b) =>
        b.width * b.height - a.width * a.height ||
        a.ids[0].localeCompare(b.ids[0]),
    );
  const area = boxes.reduce(
    (sum, b) => sum + (b.width + gap) * (b.height + gap),
    0,
  );
  const rowWidth = Math.max(
    ...boxes.map((b) => b.width),
    Math.sqrt(area * 1.8),
  );
  let x = 0,
    y = 0,
    rowHeight = 0;
  for (const box of boxes) {
    if (x > 0 && x + box.width > rowWidth) {
      x = 0;
      y += rowHeight + gap;
      rowHeight = 0;
    }
    for (const id of box.ids) {
      const point = points.get(id)!;
      point.x += x - box.minX;
      point.y += y - box.minY;
    }
    x += box.width + gap;
    rowHeight = Math.max(rowHeight, box.height);
  }
  const values = [...points.values()];
  const centerX =
    (Math.min(...values.map((p) => p.x)) +
      Math.max(...values.map((p) => p.x))) /
    2;
  const centerY =
    (Math.min(...values.map((p) => p.y)) +
      Math.max(...values.map((p) => p.y))) /
    2;
  for (const point of values) {
    point.x -= centerX;
    point.y -= centerY;
  }
}

// D-GRP-01/01b: topology determines proximity, never company names or sectors.
// Solve once in world space, independent of theme, camera and selection.
export function relationshipPositions(data: GraphResponse): Map<string, Point> {
  const cached = cache.get(data);
  if (cached) return cached;
  const ordered = [...data.nodes].sort((a, b) => a.id.localeCompare(b.id));
  const neighbors = new Map(ordered.map((n) => [n.id, new Set<string>()]));
  const pairs = new Map<
    string,
    { source: string; target: string; weight: number }
  >();
  for (const edge of data.edges) {
    if (
      !neighbors.has(edge.source) ||
      !neighbors.has(edge.target) ||
      edge.source === edge.target
    )
      continue;
    const [source, target] = [edge.source, edge.target].sort();
    const key = JSON.stringify([source, target]);
    const weight = edge.relationType === 'SHARES_ISSUE' ? 0.16 : 1;
    const previous = pairs.get(key);
    if (!previous || weight > previous.weight)
      pairs.set(key, { source, target, weight });
    if (edge.relationType !== 'SHARES_ISSUE') {
      neighbors.get(source)!.add(target);
      neighbors.get(target)!.add(source);
    }
  }
  const follows = new Set(
    data.edges
      .filter((e) => e.relationType === 'FOLLOWS')
      .flatMap((e) => [e.source, e.target]),
  );
  // Folded leaves do not crowd their parent. Their anchors are retained for expansion.
  const core = ordered.filter(
    (n) =>
      n.kind === 'company' ||
      neighbors.get(n.id)!.size > 1 ||
      follows.has(n.id),
  );
  const points = new Map<string, Point>(
    core.map((n, i) => {
      const angle = i * 2.399963229728653;
      const radius = 180 * Math.sqrt(i + 1);
      return [
        n.id,
        { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius },
      ] as const;
    }),
  );
  const links = [...pairs.values()]
    .filter((e) => points.has(e.source) && points.has(e.target))
    .sort(
      (a, b) =>
        a.source.localeCompare(b.source) || a.target.localeCompare(b.target),
    );
  const nodes = [...points.values()];
  const iterations = Math.max(
    50,
    Math.min(400, Math.floor(2400000 / Math.max(1, nodes.length ** 2))),
  );
  for (let tick = 0; tick < iterations; tick++) {
    const forces = new Map(core.map((n) => [n.id, { x: 0, y: 0 }]));
    for (let i = 0; i < core.length; i++) {
      const a = points.get(core[i].id)!;
      const forceA = forces.get(core[i].id)!;
      for (let j = i + 1; j < core.length; j++) {
        const b = points.get(core[j].id)!;
        const dx = a.x - b.x,
          dy = a.y - b.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const strength = 180 ** 2 / distance;
        const fx = (dx / distance) * strength,
          fy = (dy / distance) * strength;
        forceA.x += fx;
        forceA.y += fy;
        const forceB = forces.get(core[j].id)!;
        forceB.x -= fx;
        forceB.y -= fy;
      }
    }
    for (const edge of links) {
      const a = points.get(edge.source)!,
        b = points.get(edge.target)!;
      const dx = b.x - a.x,
        dy = b.y - a.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      // D-GRP-01: 연결이 적은 끝 노드는 촘촘한 관계 묶음보다 느슨하게 붙여요.
      const degree = Math.min(
        neighbors.get(edge.source)!.size,
        neighbors.get(edge.target)!.size,
      );
      const spacing = degree <= 1 ? 1.75 : degree === 2 ? 1.3 : 1;
      const strength = (distance ** 2 / (210 * spacing ** 3)) * edge.weight;
      const fx = (dx / distance) * strength,
        fy = (dy / distance) * strength;
      forces.get(edge.source)!.x += fx;
      forces.get(edge.source)!.y += fy;
      forces.get(edge.target)!.x -= fx;
      forces.get(edge.target)!.y -= fy;
    }
    const temperature = 30 * (1 - tick / iterations) + 0.2;
    for (const node of core) {
      const point = points.get(node.id)!,
        force = forces.get(node.id)!;
      force.x -= point.x * 0.06;
      force.y -= point.y * 0.06;
      const length = Math.max(1, Math.hypot(force.x, force.y));
      point.x += (force.x / length) * Math.min(length, temperature);
      point.y += (force.y / length) * Math.min(length, temperature);
    }
  }
  const center = nodes.length
    ? {
        x: nodes.reduce((sum, p) => sum + p.x, 0) / nodes.length,
        y: nodes.reduce((sum, p) => sum + p.y, 0) / nodes.length,
      }
    : { x: 0, y: 0 };
  // Align the network's longest axis with the landscape map viewport.
  const xx = nodes.reduce((sum, p) => sum + (p.x - center.x) ** 2, 0);
  const yy = nodes.reduce((sum, p) => sum + (p.y - center.y) ** 2, 0);
  const xy = nodes.reduce(
    (sum, p) => sum + (p.x - center.x) * (p.y - center.y),
    0,
  );
  const angle = -Math.atan2(2 * xy, xx - yy) / 2;
  for (const point of nodes) {
    const x = point.x - center.x,
      y = point.y - center.y;
    point.x = x * Math.cos(angle) - y * Math.sin(angle);
    point.y = x * Math.sin(angle) + y * Math.cos(angle);
  }
  const spanX =
    Math.max(1, ...nodes.map((p) => p.x)) -
    Math.min(0, ...nodes.map((p) => p.x));
  const spanY =
    Math.max(1, ...nodes.map((p) => p.y)) -
    Math.min(0, ...nodes.map((p) => p.y));
  // Keep the whole network explorable at the existing 53% starting zoom.
  // Bound the solver extent, then give labels extra room along the wide axis.
  const extent = Math.max(1600, Math.sqrt(nodes.length) * 230);
  const fit = Math.min(1, extent / spanX, extent / 1.6 / spanY);
  for (const point of nodes) {
    point.x *= fit * 1.45;
    point.y *= fit;
  }
  const leaves = new Map<string, number>();
  for (const node of ordered) {
    if (points.has(node.id)) continue;
    const parentId = [...neighbors.get(node.id)!][0];
    const parent = points.get(parentId);
    const index = leaves.get(parentId ?? '') ?? 0;
    leaves.set(parentId ?? '', index + 1);
    const angle = index * 2.399963229728653;
    const radius = parent
      ? 270 + Math.floor(index / 6) * 135
      : 400 + index * 100;
    points.set(node.id, {
      x: (parent?.x ?? 0) + Math.cos(angle) * radius,
      y: (parent?.y ?? 0) + Math.sin(angle) * radius,
    });
  }
  const groups: string[][] = [];
  const visited = new Set<string>();
  for (const node of ordered) {
    if (visited.has(node.id)) continue;
    const group: string[] = [];
    const queue = [node.id];
    visited.add(node.id);
    for (let index = 0; index < queue.length; index++) {
      const id = queue[index];
      group.push(id);
      for (const neighbor of [...neighbors.get(id)!].sort()) {
        if (visited.has(neighbor)) continue;
        visited.add(neighbor);
        queue.push(neighbor);
      }
    }
    groups.push(group);
  }
  compactRelationshipGroups(points, groups);
  // D-GRP-01/01b: 배율을 줄여 상쇄하지 않고, 같은 배율에서 기본 간격을 50% 넓혀요.
  for (const point of points.values()) {
    point.x *= 1.5;
    point.y *= 1.5;
  }
  cache.set(data, points);
  return points;
}
