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
  // 2026-11-04 리뷰: 넓혔던 묶음 사이 여백(418)을 다시 180으로 되돌렸어요. 멀리 흩어지지는 않아요.
  expect(isolatedNearest).toBeGreaterThanOrEqual(180 - 1e-9);
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
  // 2026-11-04 리뷰로 사건을 기업 쪽으로 15% 당겼어요(고리 반지름·간격 × 0.85).
  expect(nearest).toBeGreaterThanOrEqual(250 * 0.85);
  for (const leaf of leaves)
    expect(distance(leaf, points.get(company.id)!)).toBeGreaterThanOrEqual(
      270 * 0.85 * 1.5 - 1e-9,
    );
});

test('D-GRP-01 issues keep a minimum distance from their companies and no nodes overlap', () => {
  // 2026-11-04 리뷰: 사건은 연결된 기업에서 최소 450(가장 큰 기업 노드의 3배) 떨어지고,
  // 노드끼리는 반지름에 여백을 더한 거리만큼 떨어져요.
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const points = relationshipPositions(data);
  const kind = new Map(data.nodes.map((n) => [n.id, n.kind]));
  const ids = [...points.keys()];
  for (const edge of data.edges) {
    if (edge.relationType === 'SHARES_ISSUE') continue;
    const kinds = [kind.get(edge.source), kind.get(edge.target)];
    if (!kinds.includes('company') || !kinds.includes('issue')) continue;
    expect(
      distance(points.get(edge.source)!, points.get(edge.target)!),
    ).toBeGreaterThanOrEqual(449);
  }
  for (let i = 0; i < ids.length; i++)
    for (let j = i + 1; j < ids.length; j++) {
      const companies = [ids[i], ids[j]].filter(
        (id) => kind.get(id) === 'company',
      ).length;
      expect(
        distance(points.get(ids[i])!, points.get(ids[j])!),
      ).toBeGreaterThanOrEqual(companies === 2 ? 374 : companies ? 134 : 179);
    }
});

test('D-GRP-01 a company fans its own issues into empty space on the outer side', () => {
  // 2026-11-04 리뷰: 기업에만 연결된 사건은 고른 간격으로 놓되, 빈 바깥쪽으로 펼쳐요.
  // 기업이 이미 그린 선(공유 사건·연결 기업) 쪽으로는 뻗지 않아요.
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const points = relationshipPositions(data);
  const kind = new Map(data.nodes.map((n) => [n.id, n.kind]));
  const links = new Map<string, string[]>();
  for (const edge of data.edges)
    if (edge.relationType !== 'SHARES_ISSUE')
      for (const [a, b] of [
        [edge.source, edge.target],
        [edge.target, edge.source],
      ])
        links.set(a, [...(links.get(a) ?? []), b]);
  const linked = data.nodes.filter(
    (n) => n.kind === 'company' && (links.get(n.id)?.length ?? 0) > 0,
  );
  const middle = {
    x: linked.reduce((s, n) => s + points.get(n.id)!.x, 0) / linked.length,
    y: linked.reduce((s, n) => s + points.get(n.id)!.y, 0) / linked.length,
  };
  let checked = 0;
  for (const company of linked) {
    const own = links
      .get(company.id)!
      .filter((id) => kind.get(id) === 'issue' && links.get(id)!.length === 1);
    if (own.length === 0 || own.length > 3) continue;
    const c = points.get(company.id)!;
    const out = { x: c.x - middle.x, y: c.y - middle.y };
    if (Math.hypot(out.x, out.y) < 400) continue;
    const average = own.reduce(
      (s, id) => ({
        x: s.x + points.get(id)!.x - c.x,
        y: s.y + points.get(id)!.y - c.y,
      }),
      { x: 0, y: 0 },
    );
    // Within 120 degrees of the outward direction: the emptiest side wins over pure outward.
    expect(average.x * out.x + average.y * out.y).toBeGreaterThan(
      -0.5 * Math.hypot(average.x, average.y) * Math.hypot(out.x, out.y),
    );
    const turn = (a: { x: number; y: number }, b: { x: number; y: number }) =>
      Math.abs(Math.atan2(a.x * b.y - a.y * b.x, a.x * b.x + a.y * b.y));
    for (const line of links.get(company.id)!.filter((id) => !own.includes(id)))
      for (const id of own)
        expect(
          turn(
            { x: points.get(id)!.x - c.x, y: points.get(id)!.y - c.y },
            { x: points.get(line)!.x - c.x, y: points.get(line)!.y - c.y },
          ),
        ).toBeGreaterThan(Math.PI / 9);
    checked += 1;
  }
  expect(checked).toBeGreaterThan(0);
});
