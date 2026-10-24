import { expect, test } from 'vitest';
import { relationshipPositions } from '@/components/graph/relationship-layout';
import { toG6Data } from '@/components/graph/graph-model';
import { createMockGraph } from '@/mocks/graph/response';

const distance = (a: { x: number; y: number }, b: { x: number; y: number }) =>
  Math.hypot(a.x - b.x, a.y - b.y);

test('D-GRP-01: connected communities stay closer than disconnected communities', () => {
  const fixture = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const companies = fixture.nodes
    .filter((n) => n.kind === 'company')
    .slice(0, 4);
  const issues = fixture.nodes.filter((n) => n.kind === 'issue').slice(0, 2);
  const nodes = [...companies, ...issues];
  const edges = companies.map((node, index) => ({
    ...fixture.edges[0],
    id: `edge-${index}`,
    source: issues[Math.floor(index / 2)].id,
    target: node.id,
  }));
  const data = { ...fixture, nodes, edges };
  const positions = relationshipPositions(data);
  expect(
    distance(positions.get(companies[0].id)!, positions.get(companies[1].id)!),
  ).toBeLessThan(
    distance(positions.get(companies[0].id)!, positions.get(companies[2].id)!),
  );
  expect(positions).toEqual(
    relationshipPositions({
      ...data,
      nodes: [...nodes].reverse(),
      edges: [...edges].reverse(),
    }),
  );
});

test('D-GRP-01/01b: emphasis preserves layout and coordinates remain finite', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const before = structuredClone(data);
  const positions = relationshipPositions(data);
  expect(positions.size).toBe(data.nodes.length);
  for (const p of positions.values())
    expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
  const plain = toG6Data(data, 1200, 700);
  const focused = toG6Data(
    data,
    1200,
    700,
    null,
    [],
    new Set([data.nodes[0].id]),
  );
  expect(focused.nodes?.map((n) => [n.id, n.style?.x, n.style?.y])).toEqual(
    plain.nodes?.map((n) => [n.id, n.style?.x, n.style?.y]),
  );
  expect(relationshipPositions(data)).toBe(positions);
  expect(data).toEqual(before);
  expect(relationshipPositions({ ...data, nodes: [], edges: [] }).size).toBe(0);
});
