import { expect, test } from 'vitest';
import { createMockGraph } from '@/mocks/graph/response';
import {
  arrangeFlow,
  arrangeFocus,
  focusRings,
} from '@/components/graph/graph-arrange';
import { toG6Data } from '@/components/graph/graph-model';
import { styleGraph } from '@/components/graph/graph-appearance';
import type { GraphResponse } from '@/types/map/graph';

// D-GRP-07b 포커스 모드·D-GRP-01 [흐름 순으로 정렬]의 배치. 합성 mock 그래프.

const W = 1200;
const H = 700;
const graph = (): GraphResponse =>
  createMockGraph({ mode: 'all', personalFilter: 'all' });
const point = (
  nodes: NonNullable<ReturnType<typeof toG6Data>['nodes']>,
  id: string,
) => {
  const node = nodes.find((n) => n.id === id)!;
  return { x: Number(node.style?.x), y: Number(node.style?.y) };
};
const distance = (a: { x: number; y: number }, b: { x: number; y: number }) =>
  Math.hypot(a.x - b.x, a.y - b.y);

function focusCase(hops: 1 | 2) {
  const data = graph();
  const focusId = data.nodes.find(
    (node) =>
      node.kind === 'company' &&
      data.edges.some((e) => e.source === node.id || e.target === node.id),
  )!.id;
  const rings = focusRings(data, focusId, hops);
  // 포커스 모드는 단일 기업 사건도 보이도록 이웃 전체를 강제로 그린다.
  const rendered = toG6Data(data, W, H, focusId, [...rings.keys()]);
  return {
    data,
    focusId,
    rings,
    rendered,
    ...arrangeFocus(rendered, data, focusId, hops, W, H),
  };
}

test('포커스 1단계: 포커스 노드를 가운데, 바로 이웃만 같은 반지름의 링에 두고 나머지는 숨긴다', () => {
  const { focusId, rings, rendered, nodes, hidden } = focusCase(1);
  const center = point(nodes, focusId);
  expect(center).toEqual({ x: W / 2, y: H / 2 });
  const first = [...rings].filter(([, level]) => level === 1).map(([id]) => id);
  expect(first.length).toBeGreaterThan(0);
  const radii = first.map((id) => distance(point(nodes, id), center));
  radii.forEach((r) => expect(r).toBeCloseTo(radii[0], 5));
  for (const node of rendered.nodes ?? []) {
    const id = String(node.id);
    expect(hidden.has(id)).toBe(!rings.has(id));
  }
});

test('포커스 2단계: 이웃의 이웃은 바깥 링에 두어 1단계보다 멀다', () => {
  const { focusId, rings, nodes } = focusCase(2);
  const center = point(nodes, focusId);
  const radius = (level: number) =>
    [...rings]
      .filter(([, l]) => l === level)
      .map(([id]) => distance(point(nodes, id), center));
  expect(radius(2).length).toBeGreaterThan(0);
  expect(Math.min(...radius(2))).toBeGreaterThan(Math.max(...radius(1)));
});

test('흐름 순 정렬: 사건은 관련 기업보다, 선행 사건은 후속 사건보다 왼쪽에 있고 노드가 겹치지 않는다', () => {
  const data = graph();
  const rendered = toG6Data(data, W, H);
  const nodes = arrangeFlow(rendered, data, W, H);
  const present = new Set(nodes.map((n) => String(n.id)));
  const kind = new Map(data.nodes.map((n) => [n.id, n.kind]));
  let checked = 0;
  for (const edge of data.edges) {
    if (!present.has(edge.source) || !present.has(edge.target)) continue;
    if (edge.relationType === 'FOLLOWS') {
      // 계약의 FOLLOWS는 뒤 사건(source) → 앞 사건(target)이므로
      // 시간 순 배치는 target(선행)을 왼쪽에 둔다.
      expect(point(nodes, edge.target).x).toBeLessThan(
        point(nodes, edge.source).x,
      );
      checked += 1;
    }
    if (
      edge.relationType === 'INVOLVES' ||
      edge.relationType === 'STRUCTURALLY_RELATED_TO'
    ) {
      const issue =
        kind.get(edge.source) === 'issue' ? edge.source : edge.target;
      const company = issue === edge.source ? edge.target : edge.source;
      expect(point(nodes, issue).x).toBeLessThan(point(nodes, company).x);
      checked += 1;
    }
  }
  expect(checked).toBeGreaterThan(0);
  const keys = nodes.map((n) => `${n.style?.x}:${n.style?.y}`);
  expect(new Set(keys).size).toBe(keys.length);
});

test('흐름 순 정렬: 사건과 이어지지 않은 기업은 연결된 노드보다 오른쪽에 여러 열로 둔다', () => {
  const base = graph();
  const company = base.nodes.find((n) => n.kind === 'company')!;
  // 사건과 이어지지 않은 합성 기업 10개
  const data: GraphResponse = {
    ...base,
    nodes: [
      ...base.nodes,
      ...Array.from({ length: 10 }, (_, i) => ({
        ...company,
        id: `loose-${i}`,
        label: `합성 기업 ${i}`,
      })),
    ],
  };
  const nodes = arrangeFlow(toG6Data(data, W, H), data, W, H);
  const linked = new Set(
    data.edges
      .filter((e) => e.relationType !== 'SHARES_ISSUE')
      .flatMap((e) => [e.source, e.target]),
  );
  const loose = nodes.filter((n) => !linked.has(String(n.id)));
  const connected = nodes.filter((n) => linked.has(String(n.id)));
  expect(loose.length).toBeGreaterThan(8);
  const rightmostConnected = Math.max(
    ...connected.map((n) => Number(n.style?.x)),
  );
  loose.forEach((n) =>
    expect(Number(n.style?.x)).toBeGreaterThan(rightmostConnected),
  );
  expect(new Set(loose.map((n) => n.style?.x)).size).toBeGreaterThan(1);
});

test('flow order keeps styled (enlarged) company nodes and their labels apart in each column', () => {
  // Review #321: 5 events each tied to the same 6 companies at height 600. The improved
  // appearance enlarges companies by 15%, so the fixed 88 row gap alone would overlap them.
  const base = graph();
  const companies = base.nodes.filter((n) => n.kind === 'company').slice(0, 6);
  const issues = base.nodes.filter((n) => n.kind === 'issue').slice(0, 5);
  const template = base.edges.find((e) => e.relationType === 'INVOLVES')!;
  const data: GraphResponse = {
    ...base,
    nodes: [...companies, ...issues],
    edges: issues.flatMap((issue) =>
      companies.map((company) => ({
        ...template,
        id: `${issue.id}->${company.id}`,
        source: issue.id,
        target: company.id,
        relationType: 'INVOLVES' as const,
        derived: false,
        via: [],
      })),
    ),
  };
  const width = 1245;
  const height = 600;
  const styled = styleGraph(toG6Data(data, width, height), {
    variant: 'improved',
    theme: 'light',
  });
  const arranged = arrangeFlow(styled, data, width, height);
  const columns = new Map<number, typeof arranged>();
  for (const node of arranged)
    columns.set(Number(node.style?.x), [
      ...(columns.get(Number(node.style?.x)) ?? []),
      node,
    ]);
  const companyColumn = [...columns.values()].find((column) =>
    column.some((node) => node.id === companies[0].id),
  )!;
  expect(companyColumn).toHaveLength(6);
  const radius = (node: (typeof arranged)[number]) =>
    Number(node.style?.size) / 2;
  const sorted = [...companyColumn].sort(
    (a, b) => Number(a.style?.y) - Number(b.style?.y),
  );
  // The styled diameter is larger than the old 88 minimum gap.
  expect(2 * radius(sorted[0])).toBeGreaterThan(88);
  for (let i = 1; i < sorted.length; i += 1) {
    const upper = sorted[i - 1];
    const label =
      Number(upper.style?.labelFontSize ?? 0) * 1.4 +
      Math.abs(Number(upper.style?.labelOffsetY ?? 0));
    expect(
      Number(sorted[i].style?.y) - Number(upper.style?.y),
    ).toBeGreaterThanOrEqual(radius(upper) + label + radius(sorted[i]));
  }
});
