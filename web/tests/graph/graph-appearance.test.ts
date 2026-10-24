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

test.each(['light', 'dark'] as const)(
  'D-GRP-01: %s background links stay thinner than selected links without changing relation shapes or hit areas',
  (theme) => {
    const data = toG6Data(
      createMockGraph({ mode: 'all', personalFilter: 'all' }),
      1200,
      700,
    );
    const result = styleGraph(data, { variant: 'improved', theme });
    result.edges?.forEach((edge, index) => {
      expect(Number(edge.style?.lineWidth)).toBeLessThan(2);
      expect(edge.style?.lineDash).toEqual(data.edges?.[index].style?.lineDash);
      expect(edge.style?.endArrow).toBe(data.edges?.[index].style?.endArrow);
      expect(edge.style?.increasedLineWidthForHitTesting).toBe(
        data.edges?.[index].style?.increasedLineWidthForHitTesting,
      );
    });
  },
);

/** WCAG 대비(상대 휘도). 반투명 선은 지도 바탕과 섞은 색으로 잰다. */
function contrastOnMap(stroke: string, opacity: number, map: string) {
  const rgb = (hex: string) =>
    [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const luminance = (channels: number[]) => {
    const [r, g, b] = channels.map((value) => {
      const c = value / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const back = rgb(map);
  const mixed = rgb(stroke).map(
    (value, i) => value * opacity + back[i] * (1 - opacity),
  );
  const [high, low] = [luminance(mixed), luminance(back)].sort((a, b) => b - a);
  return (high + 0.05) / (low + 0.05);
}

test.each([
  ['light', '#fafafa'],
  ['dark', '#1c1c1e'],
] as const)(
  'D-GRP-01: %s map links keep 3:1 contrast, follow arrows stay strongest and dimmed links never exceed the inactive state',
  (theme, map) => {
    const data = toG6Data(
      createMockGraph({ mode: 'all', personalFilter: 'all' }),
      1200,
      700,
    );
    const result = styleGraph(data, { variant: 'improved', theme });
    result.edges?.forEach((edge, index) => {
      const opacity = Number(edge.style?.strokeOpacity);
      if (Number(data.edges?.[index].style?.strokeOpacity) < 0.1) {
        // G6 inactive state is 0.2: becoming inactive must not brighten a dimmed link.
        expect(opacity).toBeLessThanOrEqual(0.2);
        return;
      }
      expect(
        contrastOnMap(String(edge.style?.stroke), opacity, map),
      ).toBeGreaterThanOrEqual(3);
      if (edge.style?.endArrow) expect(opacity).toBe(0.95);
    });
  },
);
