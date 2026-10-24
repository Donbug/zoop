import { expect, test, vi } from 'vitest';
import {
  applyGraphReading,
  culledLabels,
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

test.each([0.1, 0.53, 0.8, 1.5])(
  'D-GRP-01 LOD at %s keeps visible text >=13px without moving or recoloring nodes',
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
      if (node.data?.kind === 'issue')
        expect(node.style?.labelVisibility).toBe(
          zoom < 0.55 ? 'hidden' : 'visible',
        );
    }
  },
);

test('G3/G4 selected neighborhoods, full edge summaries and null vs zero counts', () => {
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
  expect(edge?.style?.labelText).toBe(data.edges[0].summary);
  expect(edge?.style?.labelVisibility).toBe('visible');
  issue.evidenceCount = null;
  expect(
    readingStyles(base, data, { ...context, anchor: issue.id }).nodes?.find(
      (n) => n.id === issue.id,
    )?.style?.badges,
  ).toEqual([]);
});

test('G3 dense graphs show only selected/latest six or path/hover labels', () => {
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
  ).toHaveLength(6);
  expect(
    readingStyles(dense, data, {
      ...context,
      path: new Set(['dense-15']),
    }).edges?.find((e) => e.id === 'dense-15')?.style?.labelVisibility,
  ).toBe('visible');
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
