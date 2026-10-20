import type { GraphResponse } from '@/types/map/graph';

// D-GRP-07: shortest undirected connection in the returned snapshot, not causality.
// Derived SHARES_ISSUE shortcuts do not replace the underlying issue nodes.
export function companyPath(graph: GraphResponse, from: string, to: string) {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  if (
    from === to ||
    nodes.get(from)?.kind !== 'company' ||
    nodes.get(to)?.kind !== 'company'
  )
    return null;
  const neighbors = new Map<string, { id: string; edge: string }[]>();
  for (const edge of graph.edges) {
    if (
      edge.relationType === 'SHARES_ISSUE' ||
      !nodes.has(edge.source) ||
      !nodes.has(edge.target)
    )
      continue;
    for (const [a, b] of [
      [edge.source, edge.target],
      [edge.target, edge.source],
    ]) {
      const list = neighbors.get(a) ?? [];
      list.push({ id: b, edge: edge.id });
      neighbors.set(a, list);
    }
  }
  const previous = new Map<string, { id: string; edge: string }>();
  const queue = [from],
    visited = new Set(queue);
  for (let index = 0; index < queue.length && !visited.has(to); index++) {
    for (const next of neighbors.get(queue[index]) ?? []) {
      if (visited.has(next.id)) continue;
      visited.add(next.id);
      previous.set(next.id, { id: queue[index], edge: next.edge });
      queue.push(next.id);
    }
  }
  if (!visited.has(to)) return null;
  const ids = [to],
    edgeIds: string[] = [];
  while (ids[0] !== from) {
    const step = previous.get(ids[0])!;
    ids.unshift(step.id);
    edgeIds.unshift(step.edge);
  }
  return { nodes: ids.map((id) => nodes.get(id)!), edgeIds };
}
