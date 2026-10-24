import { expect, test } from 'vitest';
import { createMockGraph } from '@/mocks/graph/response';
import { toG6Data } from '@/components/graph/graph-model';
import { intersects, nodeRect } from '@/components/graph/graph-geometry';
import {
  MIN_LABEL_PX,
  defaultAppearance,
  readableLabels,
  styleGraph,
} from '@/components/graph/graph-appearance';

test('D-GRP-01: default comparison does not change the existing graph', () => {
  const data = toG6Data(
    createMockGraph({ mode: 'all', personalFilter: 'all' }),
    1200,
    700,
  );
  expect(styleGraph(data, defaultAppearance)).toBe(data);
  expect(styleGraph(data, { variant: 'original', theme: 'dark' })).toBe(data);
});

test.each(['light', 'dark'] as const)(
  'D-GRP-01: %s candidate preserves graph identities and direction while enlarging nodes and labels',
  (theme) => {
    const data = toG6Data(
      createMockGraph({ mode: 'all', personalFilter: 'all' }),
      1200,
      700,
    );
    const before = structuredClone(data);
    const candidate = styleGraph(data, { variant: 'improved', theme });
    expect(data).toEqual(before);
    expect(candidate.nodes?.map((n) => [n.id, n.style?.iconSrc])).toEqual(
      data.nodes?.map((n) => [n.id, n.style?.iconSrc]),
    );
    const nodes = candidate.nodes ?? [];
    for (const [index, node] of nodes.entries()) {
      expect(Number(node.style?.size)).toBeCloseTo(
        Number(data.nodes?.[index].style?.size) *
          (node.data?.kind === 'company' ? 1.15 : 1.1),
      );
      expect(Number(node.style?.labelFontSize)).toBeGreaterThan(
        Number(data.nodes?.[index].style?.labelFontSize),
      );
      for (const other of nodes.slice(index + 1)) {
        expect(intersects(nodeRect(node), nodeRect(other))).toBe(false);
      }
    }
    expect(
      candidate.edges?.map((e) => [
        e.id,
        e.source,
        e.target,
        e.style?.endArrow,
        e.style?.lineDash,
      ]),
    ).toEqual(
      data.edges?.map((e) => [
        e.id,
        e.source,
        e.target,
        e.style?.endArrow,
        e.style?.lineDash,
      ]),
    );
    expect(
      candidate.edges
        ?.filter((e) => !e.style?.lineDash)
        .every((e) => e.style?.lineWidth === 1.95),
    ).toBe(true);
    expect(
      candidate.edges
        ?.filter((e) => e.style?.lineDash)
        .every((e) => e.style?.lineWidth === 1.5),
    ).toBe(true);
  },
);

test('D-GRP-01: zoomed-out labels keep a readable screen size and return to their base when zoomed in', () => {
  const data = styleGraph(
    toG6Data(
      createMockGraph({ mode: 'all', personalFilter: 'all' }),
      1200,
      700,
    ),
    { variant: 'improved', theme: 'light' },
  );
  const company = data.nodes!.find((node) => node.data?.kind === 'company')!;
  const issue = data.nodes!.find((node) => node.data?.kind === 'issue')!;
  const zoomedOut = readableLabels(data, 0.4);
  const size = (graph: typeof data, id: unknown) =>
    Number(graph.nodes!.find((node) => node.id === id)!.style?.labelFontSize);
  expect(size(zoomedOut, company.id) * 0.4).toBeCloseTo(MIN_LABEL_PX.company);
  expect(size(zoomedOut, issue.id) * 0.4).toBeCloseTo(MIN_LABEL_PX.issue);
  const zoomedIn = readableLabels(zoomedOut, 2);
  expect(size(zoomedIn, company.id)).toBe(company.style?.labelFontSize);
  expect(size(zoomedIn, issue.id)).toBe(issue.style?.labelFontSize);
  // 위치·노드 크기는 바꾸지 않는다.
  expect(
    zoomedOut.nodes!.map((node) => [node.style?.x, node.style?.size]),
  ).toEqual(data.nodes!.map((node) => [node.style?.x, node.style?.size]));
});

test('D-GRP-01: dimmed context nodes are not enlarged', () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const focus = graph.nodes.find((node) => node.kind === 'company')!;
  const data = toG6Data(graph, 1200, 700, focus.id, [], new Set([focus.id]));
  const dimmed = data.nodes!.find((node) => Number(node.style?.opacity) < 1)!;
  const result = readableLabels(data, 0.3);
  expect(
    result.nodes!.find((node) => node.id === dimmed.id)!.style?.labelFontSize,
  ).toBe(dimmed.style?.labelFontSize);
});

test('D-GRP-03: the chosen company label is larger and bolder than its neighbours', () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const [chosen, other] = graph.nodes.filter((node) => node.kind === 'company');
  const data = styleGraph(toG6Data(graph, 1200, 700, chosen.id), {
    variant: 'improved',
    theme: 'light',
  });
  const styleOf = (id: string) =>
    data.nodes!.find((node) => node.id === id)!.style!;
  expect(Number(styleOf(chosen.id).labelFontSize)).toBeGreaterThan(
    Number(styleOf(other.id).labelFontSize),
  );
  expect(styleOf(chosen.id).labelFontWeight).toBe(800);
  expect(styleOf(other.id).labelFontWeight).toBe(600);
  expect(styleOf(chosen.id).labelFill).not.toBe(styleOf(other.id).labelFill);
});
