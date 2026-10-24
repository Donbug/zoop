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
        .every((e) => e.style?.lineWidth === 1.95),
    ).toBe(true);
    expect(
      candidate.edges
        ?.filter((e) => e.style?.lineDash)
        .every((e) => e.style?.lineWidth === 1.5),
    ).toBe(true);
  },
);
