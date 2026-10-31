import { expect, test, vi } from 'vitest';
import {
  applyGraphReading,
  culledLabels,
  keepAppliedStyles,
  readingStyles,
  type ReadingContext,
} from '@/components/graph/graph-readability';
import { toG6Data } from '@/components/graph/graph-model';
import { createMockGraph } from '@/mocks/graph/response';
import type { Graph, GraphData } from '@antv/g6';

const context: ReadingContext = {
  zoom: 0.53,
  anchor: null,
  edge: null,
  focus: null,
  path: new Set(),
};

test.each([0.1, 0.4, 0.53, 0.8, 1.5])(
  'D-GRP-01 company and issue labels stay visible at zoom %s with text >=13px without moving or recoloring nodes',
  (zoom) => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const base = toG6Data(data, 1200, 700);
    const result = readingStyles(base, data, { ...context, zoom });
    for (const [i, node] of (result.nodes ?? []).entries()) {
      expect(Number(node.style?.labelFontSize) * zoom).toBeGreaterThanOrEqual(
        13,
      );
      for (const key of ['x', 'y', 'fill', 'iconSrc', 'size'] as const)
        expect(node.style?.[key]).toEqual(base.nodes?.[i].style?.[key]);
      expect(node.style?.labelVisibility).toBe('visible');
    }
  },
);

test('D-GRP-01 always-visible issue names do not reveal nodes hidden by filters', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const issue = base.nodes!.find((node) => node.data?.kind === 'issue')!;
  issue.style = { ...issue.style, visibility: 'hidden' };
  const result = readingStyles(base, data, { ...context, zoom: 0.4 });
  expect(
    result.nodes!.find((node) => node.id === issue.id)?.style?.labelVisibility,
  ).toBe('hidden');
});

test('D-GRP-01 selected issue names and zero counts remain, but edge tags stay hidden', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const issue = data.nodes.find((n) => n.kind === 'issue')!;
  issue.evidenceCount = 0;
  data.edges[0].summary = '승인된 관계의 긴 설명은 생략 없이 줄바꿈해요';
  const base = toG6Data(data, 1200, 700);
  const result = readingStyles(base, data, {
    ...context,
    anchor: issue.id,
    edge: data.edges[0].id,
  });
  const selected = result.nodes?.find((n) => n.id === issue.id);
  expect(selected?.style?.labelVisibility).toBe('visible');
  expect((selected?.style?.badges as { text: string }[])[0].text).toBe('0');
  const edge = result.edges?.find((e) => e.id === data.edges[0].id);
  expect(edge?.style?.labelText).toBe('');
  expect(edge?.style?.labelVisibility).toBe('hidden');
  expect(data.edges[0].summary).toBe(
    '승인된 관계의 긴 설명은 생략 없이 줄바꿈해요',
  );
  issue.evidenceCount = null;
  expect(
    readingStyles(base, data, { ...context, anchor: issue.id }).nodes?.find(
      (n) => n.id === issue.id,
    )?.style?.badges,
  ).toEqual([]);
});

test('D-GRP-01 dense graphs never show edge tags on zoom, selection, path or hover', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const edge = base.edges![0];
  const dense = {
    ...base,
    edges: Array.from({ length: 170 }, (_, i) => ({
      ...edge,
      id: `dense-${i}`,
    })),
  };
  expect(
    readingStyles(dense, data, { ...context, zoom: 2 }).edges?.filter(
      (e) => e.style?.labelVisibility === 'visible',
    ),
  ).toHaveLength(0);
  expect(
    readingStyles(dense, data, {
      ...context,
      zoom: 2,
      anchor: String(edge.target),
    }).edges?.filter((e) => e.style?.labelVisibility === 'visible'),
  ).toHaveLength(0);
  expect(
    readingStyles(dense, data, {
      ...context,
      path: new Set(['dense-15']),
    }).edges?.find((e) => e.id === 'dense-15')?.style?.labelVisibility,
  ).toBe('hidden');
  for (const zoom of [0.1, 0.53, 1, 4]) {
    const result = readingStyles(base, data, {
      ...context,
      zoom,
      edge: String(edge.id),
      anchor: String(edge.target),
      path: new Set([String(edge.id)]),
    });
    expect(
      result.edges?.every(
        (item) =>
          item.style?.labelText === '' &&
          item.style?.labelVisibility === 'hidden',
      ),
    ).toBe(true);
  }
});

test('R1–R3 culls node and edge labels together, prioritizes selection and avoids other company bodies', () => {
  const box = { x: 0, y: 0, width: 100, height: 30 };
  const entry = (id: string, priority: number) => ({
    id,
    priority,
    box,
    distance: 0,
    degree: 0,
    evidence: 0,
  });
  const result = culledLabels(
    [
      entry('selected', 0),
      entry('company', 3),
      entry('edge', 7),
      { ...entry('far', 1), box: { ...box, x: 300 } },
    ],
    [{ id: 'body', box: { ...box, x: 300 } }],
  );
  expect([...result].sort()).toEqual(['company', 'edge', 'far']);
});

test('R1 renderer integration measures actual label bounds and hides labels without deleting nodes', async () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const attrs = new Map<string, ReturnType<typeof vi.fn>>();
  const updateLabel = vi.fn();
  for (const node of base.nodes ?? []) attrs.set(String(node.id), vi.fn());
  for (const edge of base.edges ?? []) attrs.set(String(edge.id), vi.fn());
  const graph = {
    destroyed: false,
    draw: vi.fn(async () => {}),
    updateNodeData: vi.fn(),
    updateEdgeData: vi.fn(),
    getViewportByCanvas: (p: number[]) => p,
    getCanvas: () => ({
      document: {
        getElementById: (id: string) => ({
          getShape: (name: string) => ({
            getRenderBounds: () =>
              name === 'label'
                ? { min: [10, 10], max: [100, 35] }
                : { min: [300, 300], max: [330, 330] },
            attr: attrs.get(id),
            update: name === 'label' ? updateLabel : undefined,
          }),
        }),
      },
    }),
  } as unknown as Graph;
  await applyGraphReading(graph, base, data, {
    ...context,
    zoom: 1,
    anchor: 'KRX:005930',
  });
  expect(attrs.get('KRX:005930')).not.toHaveBeenCalledWith(
    'visibility',
    'hidden',
  );
  expect(
    [...attrs.values()].some((fn) =>
      fn.mock.calls.some(
        ([key, value]) => key === 'visibility' && value === 'hidden',
      ),
    ),
  ).toBe(true);
  expect(updateLabel).toHaveBeenCalledWith(
    expect.objectContaining({ fontSize: expect.any(Number) }),
  );
  expect(graph.updateNodeData).toHaveBeenCalledWith(
    expect.arrayContaining([expect.objectContaining({ id: 'KRX:005930' })]),
  );
});

test('R1 queued reading updates preserve live drag coordinates and current edge styles', async () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const node = base.nodes![0];
  const edge = base.edges![0];
  const live = { ...node.style, x: 900, y: 777 };
  const liveEdge = { ...edge.style, stroke: '#123456', lineWidth: 7 };
  const graph = {
    destroyed: false,
    updateNodeData: (updates: NonNullable<GraphData['nodes']>) => {
      Object.assign(live, updates.find((n) => n.id === node.id)?.style);
    },
    updateEdgeData: (updates: NonNullable<GraphData['edges']>) => {
      Object.assign(liveEdge, updates.find((e) => e.id === edge.id)?.style);
    },
    draw: async () => {},
    getCanvas: () => ({ document: { getElementById: () => null } }),
  } as unknown as Graph;
  // The reading queue still holds base while drag has already moved the live model.
  await Promise.resolve().then(() =>
    applyGraphReading(graph, base, data, context),
  );
  expect([live.x, live.y]).toEqual([900, 777]);
  expect(live.labelFontSize).toBeGreaterThanOrEqual(13 / context.zoom);
  expect(liveEdge.stroke).toBe('#123456');
  expect(liveEdge.lineWidth).toBe(7);
});

test('setData keeps applied label styles and model-only keys so unchanged elements do not redraw', () => {
  const graph = {
    getNodeData: () => [
      {
        id: 'a',
        style: { x: 1, labelFontSize: 24, labelFill: '#000', zIndex: 0 },
      },
    ],
    getEdgeData: () => [
      { id: 'e', style: { sourceNode: 'a', targetNode: 'b', zIndex: -1 } },
    ],
  } as unknown as Graph;
  const next = keepAppliedStyles(graph, {
    nodes: [{ id: 'a', style: { x: 2, labelFontSize: 13, labelFill: '#fff' } }],
    edges: [{ id: 'e', source: 'a', target: 'b', style: { lineWidth: 1 } }],
  });
  // Zoom-derived label sizes stay, new colours and positions win, omitted keys come from the model.
  expect(next.nodes?.[0].style).toEqual({
    x: 2,
    labelFontSize: 24,
    labelFill: '#fff',
    zIndex: 0,
  });
  expect(next.edges?.[0].style).toEqual({
    lineWidth: 1,
    sourceNode: 'a',
    targetNode: 'b',
    zIndex: -1,
  });
});

test('setData keeps the new label of an element whose label input changed', async () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const [changed, same] = base.nodes!;
  const graph = {
    destroyed: false,
    updateNodeData: () => {},
    updateEdgeData: () => {},
    draw: async () => {},
    getCanvas: () => ({ document: { getElementById: () => null } }),
    getNodeData: () => [
      { id: changed.id, style: { ...changed.style, labelFontSize: 99 } },
      { id: same.id, style: { ...same.style, labelFontSize: 99 } },
    ],
    getEdgeData: () => [],
  } as unknown as Graph;
  await applyGraphReading(graph, base, data, context);
  const next = keepAppliedStyles(graph, {
    nodes: [
      { ...changed, style: { ...changed.style, labelText: '바뀐 이름' } },
      same,
    ],
  });
  // The changed element waits for the next reading with its new text; the other keeps the applied size.
  expect(next.nodes?.[0].style?.labelText).toBe('바뀐 이름');
  expect(next.nodes?.[0].style?.labelFontSize).toBe(
    changed.style?.labelFontSize,
  );
  expect(next.nodes?.[1].style?.labelFontSize).toBe(99);
});
