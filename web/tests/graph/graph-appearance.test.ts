import { expect, test } from 'vitest';
import { createMockGraph } from '@/mocks/graph/response';
import { toG6Data } from '@/components/graph/graph-model';
import { intersects, nodeRect } from '@/components/graph/graph-geometry';
import {
  defaultAppearance,
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
        .every((e) => e.style?.lineWidth === 1.1),
    ).toBe(true);
    expect(
      candidate.edges
        ?.filter((e) => e.style?.lineDash)
        .every((e) => e.style?.lineWidth === 1),
    ).toBe(true);
  },
);

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

test.each(['light', 'dark'] as const)(
  'D-GRP-01: %s background links stay quiet without changing relation shapes or hit areas',
  (theme) => {
    const data = toG6Data(
      createMockGraph({ mode: 'all', personalFilter: 'all' }),
      1200,
      700,
    );
    const result = styleGraph(data, { variant: 'improved', theme });
    result.edges?.forEach((edge, index) => {
      expect(Number(edge.style?.strokeOpacity)).toBeLessThanOrEqual(0.5);
      expect(Number(edge.style?.lineWidth)).toBeLessThan(2);
      expect(edge.style?.lineDash).toEqual(data.edges?.[index].style?.lineDash);
      expect(edge.style?.endArrow).toBe(data.edges?.[index].style?.endArrow);
      expect(edge.style?.increasedLineWidthForHitTesting).toBe(
        data.edges?.[index].style?.increasedLineWidthForHitTesting,
      );
    });
  },
);
