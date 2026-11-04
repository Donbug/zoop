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

test('D-GRP-01: sparse links get more room than a densely connected neighborhood', () => {
  const fixture = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const companies = fixture.nodes
    .filter((node) => node.kind === 'company')
    .slice(0, 5);
  const issues = fixture.nodes
    .filter((node) => node.kind === 'issue')
    .slice(0, 3);
  const denseEdges = issues.flatMap((issue, i) =>
    companies.slice(0, 3).map((company, j) => ({
      ...fixture.edges[0],
      id: `dense-${i}-${j}`,
      source: issue.id,
      target: company.id,
      relationType: 'INVOLVES' as const,
    })),
  );
  const sparseEdge = {
    ...denseEdges[0],
    id: 'sparse',
    target: companies[3].id,
  };
  const graph = {
    ...fixture,
    nodes: [...companies, ...issues],
    edges: [...denseEdges, sparseEdge],
  };
  const points = relationshipPositions(graph);
  const length = (edge: typeof sparseEdge) =>
    distance(points.get(edge.source)!, points.get(edge.target)!);
  const denseMean =
    denseEdges.reduce((sum, edge) => sum + length(edge), 0) / denseEdges.length;
  const isolatedNearest = Math.min(
    ...graph.nodes
      .filter((node) => node.id !== companies[4].id)
      .map((node) =>
        distance(points.get(node.id)!, points.get(companies[4].id)!),
      ),
  );
  // 이 합성 그래프에서 변경 전에 측정한 밀집 구간 평균 거리예요. 요청한 30% 이상 확대를 확인해요.
  const previousDenseMean = 191.91688130435122;
  expect(denseMean).toBeGreaterThanOrEqual(previousDenseMean * 1.3);
  expect(length(sparseEdge)).toBeGreaterThan(denseMean * 1.5);
  // 2026-11-04 리뷰: 묶음 사이 여백을 180에서 418로 넓혔어요(55%, 다시 50%). 멀리 흩어지지는 않아요.
  expect(isolatedNearest).toBeGreaterThanOrEqual(180 * 1.55 * 1.5 - 1e-9);
  expect(isolatedNearest).toBeLessThanOrEqual(1200);
});

test('D-GRP-01: a busy company spreads its single-company issues around fuller rings', () => {
  // 2026-11-04 공개 그래프: 삼성전자에만 연결된 사건이 19개였어요.
  const fixture = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const company = fixture.nodes.find((node) => node.kind === 'company')!;
  const issue = fixture.nodes.find((node) => node.kind === 'issue')!;
  const issues = Array.from({ length: 19 }, (_, index) => ({
    ...issue,
    id: `issue-busy-${String(index).padStart(2, '0')}`,
  }));
  const graph = {
    ...fixture,
    nodes: [company, ...issues],
    edges: issues.map((node, index) => ({
      ...fixture.edges[0],
      id: `busy-${index}`,
      source: node.id,
      target: company.id,
      relationType: 'INVOLVES' as const,
    })),
  };
  const points = relationshipPositions(graph);
  const leaves = issues.map((node) => points.get(node.id)!);
  const nearest = Math.min(
    ...leaves.flatMap((a, i) => leaves.slice(i + 1).map((b) => distance(a, b))),
  );
  // 고리마다 6개씩 황금각으로 놓던 이전 배치는 가장 가까운 두 사건이 약 227까지 붙었어요.
  expect(nearest).toBeGreaterThanOrEqual(250);
  for (const leaf of leaves)
    expect(distance(leaf, points.get(company.id)!)).toBeGreaterThanOrEqual(
      270 * 1.5 - 1e-9,
    );
});
