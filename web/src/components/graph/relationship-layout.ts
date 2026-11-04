import type { GraphResponse } from '@/types/map/graph';

type Point = { x: number; y: number };
const cache = new WeakMap<GraphResponse, Map<string, Point>>();

// Leaf-issue rings before the final 1.5× spread: first radius, ring gap and the arc reserved
// per issue title (about one wrapped title wide at the default zoom).
// D-GRP-01 (2026-11-04 review): the wider #546 spacing looked scattered on the public graph,
// so spacing is back to the earlier map and company nodes grow instead (graph-model).
// A later review the same day pulled issues 15% closer to their company and pushed
// companies 25% further from each other (COMPANY_SPREAD).
// The next review (2026-11-04, knowledge-graph reference) asked for a wide map like the
// reference: issues about 3-4 company diameters from their company, companies sharing an
// issue close and unrelated companies far apart (UNRELATED_REPULSION). The canvas is wide
// and the minimap covers navigation.
const LEAF_PULL = 0.85;
const LEAF_REACH = 1.6;
const COMPANY_SPREAD = 1.25 * 1.4;
const UNRELATED_REPULSION = 2.5;
const LEAF_RADIUS = 270 * LEAF_PULL * LEAF_REACH;
const LEAF_RING_GAP = 170 * LEAF_PULL * 1.4;
const LEAF_ARC = 260;
/** Angle between neighbouring issues on a fan that faces away from the map centre. */
const LEAF_FAN_STEP = Math.PI / 4;
const ringCapacity = (radius: number) =>
  Math.max(4, Math.floor((2 * Math.PI * radius) / LEAF_ARC));

type RankedNode = GraphResponse['nodes'][number];
/** D-GRP-01: more evidence first, then the latest event; ties keep a stable id order. */
export function leafRank(a: RankedNode, b: RankedNode) {
  return (
    (b.evidenceCount ?? 0) - (a.evidenceCount ?? 0) ||
    (b.eventTime ?? '').localeCompare(a.eventTime ?? '') ||
    a.id.localeCompare(b.id)
  );
}

// D-GRP-01 (2026-11-04 review): busy companies that share many issues used to pile up in
// one knot of crossing lines. Keep every pair of companies at least this far apart (before
// the final 1.5x), about twice the largest company node, then carry each shared issue
// along with the companies it joins.
const MIN_COMPANY_GAP = 250;

// D-GRP-01 (2026-11-04 review): every issue keeps a minimum distance from the companies it
// joins, and no two nodes overlap. Distances are before the final 1.5x: an issue stays
// 450 world units from its company (3x the largest company node) and clears other
// nodes by their radii (company up to 75, issue 24 world units) plus a margin.
const ISSUE_REACH = 450 / 1.5;
const COMPANY_CLEARANCE = (75 + 24 + 36) / 1.5;
// Two issue diamonds (48 world units) stay at least 180 apart: about 2.7 diamonds of gap
// (2026-11-04 review: diamonds side by side were hard to tell apart).
const ISSUE_CLEARANCE = 180 / 1.5;
function spreadNodes(
  ids: string[],
  isCompany: (id: string) => boolean,
  neighbors: Map<string, Set<string>>,
  points: Map<string, Point>,
  companiesMove: boolean,
) {
  const minimum = (a: string, b: string) => {
    const companyA = isCompany(a),
      companyB = isCompany(b);
    if (companyA && companyB) return MIN_COMPANY_GAP;
    if (companyA || companyB)
      return neighbors.get(a)!.has(b) ? ISSUE_REACH : COMPANY_CLEARANCE;
    return ISSUE_CLEARANCE;
  };
  for (let round = 0; round < 200; round++) {
    let moved = false;
    for (let i = 0; i < ids.length; i++)
      for (let j = i + 1; j < ids.length; j++) {
        const need = minimum(ids[i], ids[j]);
        const a = points.get(ids[i])!,
          b = points.get(ids[j])!;
        const dx = b.x - a.x,
          dy = b.y - a.y;
        const distance = Math.hypot(dx, dy);
        if (distance >= need - 0.5) continue;
        const [ux, uy] =
          distance > 0.01
            ? [dx / distance, dy / distance]
            : [Math.cos(i * 7 + j), Math.sin(i * 7 + j)];
        // An issue gives way more than a company; fixed companies never move.
        const weight = (id: string) =>
          isCompany(id) ? (companiesMove ? 1 : 0) : 3;
        const wa = weight(ids[i]),
          wb = weight(ids[j]);
        if (wa + wb === 0) continue;
        const push = need - distance;
        a.x -= ux * push * (wa / (wa + wb));
        a.y -= uy * push * (wa / (wa + wb));
        b.x += ux * push * (wb / (wa + wb));
        b.y += uy * push * (wb / (wa + wb));
        moved = true;
      }
    if (!moved) break;
  }
}
function separateCompanies(
  core: GraphResponse['nodes'],
  neighbors: Map<string, Set<string>>,
  points: Map<string, Point>,
) {
  const companies = core.filter((n) => n.kind === 'company');
  const before = new Map(
    companies.map((n) => [n.id, { ...points.get(n.id)! }]),
  );
  for (let round = 0; round < 200; round++) {
    let moved = false;
    for (let i = 0; i < companies.length; i++)
      for (let j = i + 1; j < companies.length; j++) {
        const a = points.get(companies[i].id)!,
          b = points.get(companies[j].id)!;
        const dx = b.x - a.x,
          dy = b.y - a.y;
        const distance = Math.hypot(dx, dy);
        if (distance >= MIN_COMPANY_GAP) continue;
        // Coincident companies split along a stable direction from their order.
        const [ux, uy] =
          distance > 0.01
            ? [dx / distance, dy / distance]
            : [Math.cos(i + j), Math.sin(i + j)];
        const push = (MIN_COMPANY_GAP - distance) / 2;
        a.x -= ux * push;
        a.y -= uy * push;
        b.x += ux * push;
        b.y += uy * push;
        moved = true;
      }
    if (!moved) break;
  }
  for (const node of core) {
    if (node.kind === 'company') continue;
    const joined = [...neighbors.get(node.id)!].filter((id) => before.has(id));
    if (!joined.length) continue;
    const point = points.get(node.id)!;
    point.x +=
      joined.reduce(
        (sum, id) => sum + points.get(id)!.x - before.get(id)!.x,
        0,
      ) / joined.length;
    point.y +=
      joined.reduce(
        (sum, id) => sum + points.get(id)!.y - before.get(id)!.y,
        0,
      ) / joined.length;
  }
}

// D-GRP-01/01b: translate whole disconnected groups, never scale their interior.
// Bounds include folded issues so expanding one does not move neighboring groups.
export function compactRelationshipGroups(
  points: Map<string, Point>,
  groups: string[][],
) {
  if (groups.length < 2) return;
  // 최종 1.5배 확대를 적용하면 묶음 사이 여백은 180이 돼요.
  const gap = 120;
  const minSide = 120;
  const boxes = groups
    .map((ids) => {
      const members = ids.map((id) => points.get(id)!);
      const minX = Math.min(...members.map((p) => p.x));
      const minY = Math.min(...members.map((p) => p.y));
      const width = Math.max(
        minSide,
        Math.max(...members.map((p) => p.x)) - minX,
      );
      const height = Math.max(
        minSide,
        Math.max(...members.map((p) => p.y)) - minY,
      );
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
  // D-GRP-01 (2026-11-04 review): companies without any issue (catalog-only, #543) stay out
  // of the solver. They used to push one side of the network, so all of 삼성전자's
  // connections ended up in one direction. Group packing places them afterwards.
  const core = ordered.filter(
    (n) =>
      (n.kind === 'company' && neighbors.get(n.id)!.size > 0) ||
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
  // Two companies are related when one links to the other or they share an issue.
  const related = (a: string, b: string) =>
    neighbors.get(a)!.has(b) ||
    [...neighbors.get(a)!].some((id) => neighbors.get(id)!.has(b));
  const repulsion = new Float64Array(core.length * core.length).fill(1);
  for (let i = 0; i < core.length; i++)
    for (let j = i + 1; j < core.length; j++)
      if (
        core[i].kind === 'company' &&
        core[j].kind === 'company' &&
        !related(core[i].id, core[j].id)
      )
        repulsion[i * core.length + j] = UNRELATED_REPULSION;
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
        const strength = (180 ** 2 / distance) * repulsion[i * core.length + j];
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
  const extent = Math.max(1600, Math.sqrt(nodes.length) * 230) * 1.4;
  const fit = Math.min(1, extent / spanX, extent / 1.6 / spanY);
  for (const point of nodes) {
    point.x *= fit * 1.45 * COMPANY_SPREAD;
    point.y *= fit * COMPANY_SPREAD;
  }
  separateCompanies(core, neighbors, points);
  const companyIds = new Set(
    data.nodes.filter((n) => n.kind === 'company').map((n) => n.id),
  );
  const isCompany = (id: string) => companyIds.has(id);
  spreadNodes(
    core.map((n) => n.id),
    isCompany,
    neighbors,
    points,
    true,
  );
  // D-GRP-01: a company's single-company issues sit on rings around it. Each ring holds as many
  // as its circumference allows (one issue title per LEAF_ARC), so a busy company such as
  // 삼성전자 spreads its issues outward instead of stacking six per ring.
  const leafCounts = new Map<string, number>();
  for (const node of ordered)
    if (!points.has(node.id)) {
      const parentId = [...neighbors.get(node.id)!][0] ?? '';
      leafCounts.set(parentId, (leafCounts.get(parentId) ?? 0) + 1);
    }
  const leaves = new Map<string, number>();
  const middle = core.length
    ? {
        x: core.reduce((sum, n) => sum + points.get(n.id)!.x, 0) / core.length,
        y: core.reduce((sum, n) => sum + points.get(n.id)!.y, 0) / core.length,
      }
    : { x: 0, y: 0 };
  const fans = new Map<string, number>();
  /** Fan centre for a company's own issues: the emptiest side, leaning outward. */
  const fanDirection = (
    parentId: string,
    parent: Point,
    slots: number,
    step: number,
    radius: number,
  ) => {
    const outward =
      Math.hypot(parent.x - middle.x, parent.y - middle.y) > 1
        ? Math.atan2(parent.y - middle.y, parent.x - middle.x)
        : -Math.PI / 2;
    const others = [...points].filter(([id]) => id !== parentId);
    // Lines the company already draws to shared issues and linked companies.
    const lines = [...neighbors.get(parentId)!]
      .filter((id) => points.has(id))
      .map((id) =>
        Math.atan2(points.get(id)!.y - parent.y, points.get(id)!.x - parent.x),
      );
    const turn = (a: number, b: number) =>
      Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));
    let best = outward,
      bestScore = Infinity;
    for (let k = 0; k < 72; k++) {
      const facing = outward + (k * Math.PI) / 36;
      let score = -0.6 * slots * Math.cos(facing - outward);
      for (let slot = 0; slot < slots; slot++) {
        const angle = facing + (slot - (slots - 1) / 2) * step;
        for (const reach of [radius, radius * 1.5]) {
          const x = parent.x + Math.cos(angle) * reach,
            y = parent.y + Math.sin(angle) * reach;
          for (const [, q] of others)
            score += Math.max(0, 1 - Math.hypot(q.x - x, q.y - y) / 320) ** 2;
        }
        for (const line of lines)
          score += Math.exp(-((turn(angle, line) / 0.35) ** 2));
      }
      if (score < bestScore - 1e-9) {
        best = facing;
        bestScore = score;
      }
    }
    return best;
  };
  // The issues kept on a folded map (leafRank) take the inner ring next to their company.
  for (const node of [...ordered].sort(leafRank)) {
    if (points.has(node.id)) continue;
    const parentId = [...neighbors.get(node.id)!][0];
    const parent = points.get(parentId);
    const index = leaves.get(parentId ?? '') ?? 0;
    leaves.set(parentId ?? '', index + 1);
    if (!parent) {
      const angle = index * 2.399963229728653;
      const radius = 400 + index * 100;
      points.set(node.id, {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      });
      continue;
    }
    let ring = 0,
      start = 0,
      radius = LEAF_RADIUS,
      capacity = ringCapacity(radius);
    while (index >= start + capacity) {
      start += capacity;
      ring += 1;
      radius = LEAF_RADIUS + ring * LEAF_RING_GAP;
      capacity = ringCapacity(radius);
    }
    const onRing = Math.min(capacity, (leafCounts.get(parentId) ?? 0) - start);
    // D-GRP-01 (2026-11-04 review): issues keep even spacing but fan out into the emptiest
    // side of their company, preferring the map's outside. A full ring still uses the whole circle.
    const step = Math.min((Math.PI * 2) / onRing, LEAF_FAN_STEP);
    const facing =
      fans.get(parentId) ??
      fans
        .set(parentId, fanDirection(parentId, parent, onRing, step, radius))
        .get(parentId)!;
    // Offset alternate rings by half a slot so titles on neighbouring rings do not line up.
    const angle =
      facing + (index - start - (onRing - 1) / 2 + (ring % 2) / 2) * step;
    points.set(node.id, {
      x: parent.x + Math.cos(angle) * radius,
      y: parent.y + Math.sin(angle) * radius,
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
  // Leaves sit on rings; clear their overlaps inside each group without moving companies.
  for (const group of groups)
    if (group.length > 1)
      spreadNodes(group, isCompany, neighbors, points, false);
  compactRelationshipGroups(points, groups);
  // D-GRP-01/01b: 배율을 줄여 상쇄하지 않고, 같은 배율에서 기본 간격을 50% 넓혀요.
  for (const point of points.values()) {
    point.x *= 1.5;
    point.y *= 1.5;
  }
  cache.set(data, points);
  return points;
}
