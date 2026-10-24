import { expect, test } from 'vitest';
import {
  compactRelationshipGroups,
  relationshipPositions,
} from '@/components/graph/relationship-layout';
import { toG6Data } from '@/components/graph/graph-model';
import { createMockGraph } from '@/mocks/graph/response';

const distance = (a: { x: number; y: number }, b: { x: number; y: number }) =>
  Math.hypot(a.x - b.x, a.y - b.y);

test('D-GRP-01: packing closes empty space between groups without shrinking internal spacing', () => {
  const points = new Map([
    ['a', { x: 0, y: 0 }],
    ['b', { x: 320, y: 220 }],
    ['c', { x: 3000, y: 0 }],
    ['d', { x: 3320, y: 220 }],
  ]);
  const before = structuredClone(points);
  compactRelationshipGroups(points, [
    ['a', 'b'],
    ['c', 'd'],
  ]);
  for (const [first, second] of [
    ['a', 'b'],
    ['c', 'd'],
  ]) {
    expect(points.get(second)!.x - points.get(first)!.x).toBeCloseTo(
      before.get(second)!.x - before.get(first)!.x,
    );
    expect(points.get(second)!.y - points.get(first)!.y).toBeCloseTo(
      before.get(second)!.y - before.get(first)!.y,
    );
  }
  expect(distance(points.get('a')!, points.get('c')!)).toBeLessThan(1000);
  expect(distance(points.get('a')!, points.get('c')!)).toBeGreaterThan(320);
});

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
