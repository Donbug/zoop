import { expect, test } from 'vitest';
import { createMockGraph } from '@/mocks/graph/response';
import {
  arrangeFlow,
  arrangeFocus,
  FOCUS_CENTER_MAX,
  FOCUS_NEIGHBOR_MAX,
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

function styledFocusCase(hops: 1 | 2) {
  const data = graph();
  // 연결이 가장 많은 기업: 사건 수가 많아 지도에서 가장 큰 노드다.
  const degree = (id: string) =>
    data.edges.filter((e) => e.source === id || e.target === id).length;
  const focusId = data.nodes
    .filter((node) => node.kind === 'company')
    .sort((a, b) => degree(b.id) - degree(a.id))[0].id;
  const rings = focusRings(data, focusId, hops);
  const rendered = styleGraph(
    toG6Data(data, W, H, focusId, [...rings.keys()]),
    {
      variant: 'improved',
      theme: 'light',
    },
  );
  return {
    focusId,
    rings,
    rendered,
    ...arrangeFocus(rendered, data, focusId, hops, W, H),
  };
}
const sizeOf = (
  nodes: NonNullable<ReturnType<typeof toG6Data>['nodes']>,
  id: string,
) => Number(nodes.find((n) => n.id === id)!.style?.size);

test('포커스: 가운데 기업과 이웃 노드를 지름 상한까지 줄이고 로고도 같은 비율로 줄인다', () => {
  const { focusId, rings, rendered, nodes } = styledFocusCase(1);
  const original = sizeOf(rendered.nodes ?? [], focusId);
  expect(original).toBeGreaterThan(FOCUS_CENTER_MAX);
  expect(sizeOf(nodes, focusId)).toBe(FOCUS_CENTER_MAX);
  const before = rendered.nodes!.find((n) => n.id === focusId)!.style!;
  const after = nodes.find((n) => n.id === focusId)!.style!;
  if (typeof before.iconWidth === 'number')
    expect(Number(after.iconWidth)).toBeCloseTo(
      (before.iconWidth * FOCUS_CENTER_MAX) / original,
      5,
    );
  for (const id of rings.keys())
    if (id !== focusId)
      expect(sizeOf(nodes, id)).toBeLessThanOrEqual(FOCUS_NEIGHBOR_MAX);
});

test.each([1, 2] as const)(
  '포커스 %i단계: 보이는 노드끼리 겹치지 않는다',
  (hops) => {
    const { nodes, hidden } = styledFocusCase(hops);
    const shown = nodes.filter((n) => !hidden.has(String(n.id)));
    for (let i = 0; i < shown.length; i += 1)
      for (let j = i + 1; j < shown.length; j += 1) {
        const a = shown[i];
        const b = shown[j];
        expect(
          distance(point(nodes, String(a.id)), point(nodes, String(b.id))),
        ).toBeGreaterThanOrEqual(
          (Number(a.style?.size) + Number(b.style?.size)) / 2,
        );
      }
  },
);

test('포커스: 크기가 다른 노드가 한 링에 섞여도 이웃한 큰 노드끼리 겹치지 않는다', () => {
  // #576 리뷰: 짧은 화면, 한 링에 지름 100 기업 2개(서로 이웃)와 지름 14 사건 18개.
  const width = 600;
  const height = 300;
  const node = (id: string, size: number, angle: number) => ({
    id,
    style: { x: Math.cos(angle) * 300, y: Math.sin(angle) * 300, size },
  });
  const neighbors = [
    node('company-a', 100, 0),
    node('company-b', 100, 0.05),
    ...Array.from({ length: 18 }, (_, i) =>
      node(`issue-${i}`, 14, 0.2 + (i * (2 * Math.PI - 0.4)) / 18),
    ),
  ];
  const rendered = {
    nodes: [{ id: 'focus', style: { x: 0, y: 0, size: 100 } }, ...neighbors],
  };
  const data = {
    nodes: [],
    edges: neighbors.map((n) => ({ source: 'focus', target: n.id })),
  } as unknown as GraphResponse;
  const { nodes } = arrangeFocus(rendered, data, 'focus', 1, width, height);
  for (let i = 0; i < nodes.length; i += 1)
    for (let j = i + 1; j < nodes.length; j += 1) {
      const a = nodes[i];
      const b = nodes[j];
      expect(
        distance(point(nodes, String(a.id)), point(nodes, String(b.id))),
      ).toBeGreaterThanOrEqual(
        (Number(a.style?.size) + Number(b.style?.size)) / 2,
      );
    }
  // 두 기업은 원래 지도 방향대로 링에서도 이웃한다.
  const order = [...neighbors]
    .map((n) => ({
      id: n.id,
      angle: Math.atan2(
        point(nodes, n.id).y - height / 2,
        point(nodes, n.id).x - width / 2,
      ),
    }))
    .sort((a, b) => a.angle - b.angle)
    .map((n) => n.id);
  const ia = order.indexOf('company-a');
  const ib = order.indexOf('company-b');
  expect([1, order.length - 1]).toContain(Math.abs(ia - ib));
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
