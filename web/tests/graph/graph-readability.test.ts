import { expect, test, vi } from 'vitest';
import {
  applyGraphReading,
  culledLabels,
  keepAppliedStyles,
  OVERVIEW_ZOOM,
  readingStyles,
  type ReadingContext,
} from '@/components/graph/graph-readability';
import {
  graphSummary as graphSummaryOf,
  toG6Data,
} from '@/components/graph/graph-model';
import { intersects } from '@/components/graph/graph-geometry';
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
  'D-GRP-01 company labels stay visible at zoom %s (issue titles only from the overview zoom up) with text >=13px without moving or recoloring nodes',
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
      expect(node.style?.labelVisibility).toBe(
        node.data?.kind === 'issue' && zoom < OVERVIEW_ZOOM
          ? 'hidden'
          : 'visible',
      );
    }
  },
);

test('D-GRP-01 zoomed out, issues keep only their circle until hovered or selected', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const issue = data.nodes.find((n) => n.kind === 'issue')!;
  const style = (anchor: string | null) =>
    readingStyles(base, data, { ...context, zoom: 0.2, anchor }).nodes!.find(
      (node) => node.id === issue.id,
    )!.style!;
  expect(style(null).labelVisibility).toBe('hidden');
  expect(style(null).badges ?? []).toEqual([]);
  expect(style(issue.id).labelVisibility).toBe('visible');
});

test('D-GRP-01 the whole-graph fit shows issue circles only, even above the overview zoom', () => {
  // 2026-11-04 리뷰: 촘촘한 지도는 0.45보다 크게 맞춰져도 전체 맞춤에서는 사건 제목을 숨겨요.
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const issue = data.nodes.find((n) => n.kind === 'issue')!;
  const visibility = (zoom: number) =>
    readingStyles(base, data, {
      ...context,
      zoom,
      wholeFitZoom: 0.6,
    }).nodes!.find((node) => node.id === issue.id)!.style!.labelVisibility;
  expect(visibility(0.6)).toBe('hidden');
  expect(visibility(0.7)).toBe('hidden');
  expect(visibility(0.75)).toBe('visible');
});

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

test('D-GRP-01 titles connected to the hovered or selected node are never culled', () => {
  // 2026-11-04 리뷰: 머무르거나 클릭한 노드에 연결된 사건 제목은 겹쳐도 계속 보여요.
  const box = { x: 0, y: 0, width: 100, height: 30 };
  const entry = (id: string, priority: number, keep = false) => ({
    id,
    priority,
    box,
    distance: 0,
    degree: 0,
    evidence: 0,
    keep,
  });
  const result = culledLabels(
    [
      entry('company', 1),
      entry('linked-a', 5, true),
      entry('linked-b', 5, true),
      entry('other', 6),
    ],
    [],
  );
  expect([...result]).toEqual(['other']);
});

test('D-GRP-01 kept titles slide apart instead of printing over one another', () => {
  // 2026-11-05: 연결된 제목은 계속 보이되, 네 방향이 모두 차면 빈자리까지 밀어 겹치지 않게 둔다.
  const side = (placement: 'top' | 'bottom' | 'left' | 'right') => ({
    placement,
    box:
      placement === 'top'
        ? { x: 50, y: 60, width: 100, height: 30 }
        : placement === 'bottom'
          ? { x: 50, y: 140, width: 100, height: 30 }
          : placement === 'left'
            ? { x: -55, y: 85, width: 100, height: 30 }
            : { x: 155, y: 85, width: 100, height: 30 },
  });
  const alternatives = (['top', 'bottom', 'left', 'right'] as const).map(side);
  const ids = ['a', 'b', 'c', 'd', 'e', 'f', 'g'];
  const placements = new Map<string, 'top' | 'bottom' | 'left' | 'right'>();
  const shifts = new Map<string, number>();
  const hidden = culledLabels(
    ids.map((id) => ({
      id,
      priority: 5,
      box: alternatives[0].box,
      distance: 0,
      degree: 0,
      evidence: 0,
      keep: true,
      alternatives,
    })),
    [{ id: 'circle', box: { x: 85, y: 85, width: 30, height: 30 } }],
    placements,
    shifts,
  );
  expect([...hidden]).toEqual([]);
  expect(shifts.size).toBeGreaterThan(0);
  const boxes = ids.map((id) => {
    const box = side(placements.get(id) ?? 'top').box;
    return { ...box, y: box.y + (shifts.get(id) ?? 0) };
  });
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++)
      expect(intersects(boxes[i], boxes[j], 2)).toBe(false);
});

test('D-GRP-01 a selection keeps its connected titles while another node is hovered', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const kind = (id: string) => data.nodes.find((n) => n.id === id)?.kind;
  const link = data.edges.find(
    (e) => new Set([kind(e.source), kind(e.target)]).size === 2,
  )!;
  const [company, issue] =
    kind(link.source) === 'company'
      ? [link.source, link.target]
      : [link.target, link.source];
  const other = data.nodes.find(
    (n) =>
      n.kind === 'company' &&
      !data.edges.some(
        (e) =>
          (e.source === n.id || e.target === n.id) &&
          (e.source === issue || e.target === issue),
      ),
  )!;
  const visibility = (selected: string | null) =>
    readingStyles(base, data, {
      ...context,
      zoom: 0.2,
      anchor: other.id,
      selected,
    }).nodes!.find((node) => node.id === issue)!.style!.labelVisibility;
  expect(visibility(null)).toBe('hidden');
  expect(visibility(company)).toBe('visible');
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

test.each([0.53, 1, 1.5])(
  'D-GRP-01 selection redraw preserves issue pill reading styles at zoom %s',
  async (zoom) => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const base = toG6Data(data, 1200, 700);
    let nodes = structuredClone(base.nodes!);
    const update = vi.fn((updates: NonNullable<GraphData['nodes']>) => {
      nodes = nodes.map((node) => ({
        ...node,
        style: {
          ...node.style,
          ...updates.find((item) => item.id === node.id)?.style,
        },
      }));
    });
    const graph = {
      destroyed: false,
      getNodeData: () => nodes,
      getEdgeData: () => [],
      updateNodeData: update,
      updateEdgeData: vi.fn(),
      draw: async () => {},
      getCanvas: () => ({ document: { getElementById: () => null } }),
    } as unknown as Graph;
    const reading = { ...context, zoom };
    await applyGraphReading(graph, base, data, reading);
    const issue = data.nodes.find((node) => node.kind === 'issue')!;
    const expected = nodes.find((node) => node.id === issue.id)!.style!;
    const nextBase = toG6Data(data, 1200, 700, 'KRX:005930');
    nodes = keepAppliedStyles(graph, nextBase).nodes!;
    await applyGraphReading(graph, nextBase, data, reading);
    const actual = nodes.find((node) => node.id === issue.id)!.style!;
    for (const key of [
      'labelFontSize',
      'labelPadding',
      'labelBackgroundRadius',
      'labelBackgroundLineWidth',
    ])
      expect(actual[key]).toEqual(expected[key]);
  },
);

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

test('D-GRP-01 wrapped label lines grow with the zoom-corrected font and the overview keeps two lines', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const issue = data.nodes.find((n) => n.kind === 'issue')!;
  const company = data.nodes.find((n) => n.kind === 'company')!;
  const style = (zoom: number, id: string, anchor: string | null = null) =>
    readingStyles(base, data, { ...context, zoom, anchor }).nodes!.find(
      (node) => node.id === id,
    )!.style!;
  for (const zoom of [0.2, 0.53, 1.5]) {
    const issueStyle = style(zoom, issue.id);
    // G draws wrapped lines 16px apart by default; at 0.2 the font is 65px.
    expect(Number(issueStyle.labelLineHeight)).toBeGreaterThan(
      Number(issueStyle.labelFontSize),
    );
  }
  expect(style(0.2, issue.id).labelTextOverflow).toBe('ellipsis');
  // D-GRP-01 (2026-11-05): issue titles wrap to at most two lines at any zoom, hovered or not;
  // company names never wrap.
  for (const zoom of [0.2, 0.53, 2.5]) {
    expect(style(zoom, issue.id).labelMaxLines).toBe(2);
    expect(style(zoom, issue.id, issue.id).labelMaxLines).toBe(2);
    expect(style(zoom, issue.id).labelWordWrap).toBe(true);
    expect(style(zoom, company.id).labelWordWrap).toBe(false);
    expect(style(zoom, company.id).labelMaxLines).toBe(1);
  }
});

test('D-GRP-01 issue titles break at the same place at any zoom: wrap width follows the font', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const issue = data.nodes.find((n) => n.kind === 'issue')!;
  const style = (zoom: number) =>
    readingStyles(base, data, { ...context, zoom }).nodes!.find(
      (node) => node.id === issue.id,
    )!.style!;
  // Zoomed far in, the font stops shrinking at its map size; the wrap width used to keep
  // shrinking (170 / zoom), so titles broke into more lines the closer the user looked.
  for (const zoom of [0.2, 1, 2.5]) {
    const s = style(zoom);
    expect(Number(s.labelWordWrapWidth) / Number(s.labelFontSize)).toBeCloseTo(
      170 / 13,
      5,
    );
  }
  expect(Number(style(2.5).labelWordWrapWidth)).toBeGreaterThan(170 / 2.5);
});

/** A renderer whose labels all share one box (or each get their own), recording shape visibility. */
function cullingGraph() {
  const room = { overlap: true };
  const shapes = new Map<string, { style: { visibility?: string } }>();
  let slot = 0;
  const shape = (id: string, name: string) => {
    const key = `${id}/${name}`;
    if (!shapes.has(key)) shapes.set(key, { style: {} });
    const entry = shapes.get(key)!;
    const offset = room.overlap ? 0 : (slot += 400);
    return {
      ...entry,
      style: entry.style,
      getRenderBounds: () =>
        name === 'label'
          ? { min: [offset, 10], max: [offset + 90, 35] }
          : { min: [-5000, -5000], max: [-4990, -4990] },
      attr: () => {},
    };
  };
  const graph = {
    destroyed: false,
    draw: async () => {},
    updateNodeData: () => {},
    updateEdgeData: () => {},
    getViewportByCanvas: (p: number[]) => p,
    getCanvas: () => ({
      document: {
        getElementById: (id: string) => ({
          getShape: (name: string) => shape(id, name),
        }),
      },
    }),
  } as unknown as Graph;
  const visible = (id: string, name: string) =>
    shapes.get(`${id}/${name}`)?.style.visibility !== 'hidden';
  return { graph, visible, room };
}

test('D-GRP-01 selected company neighbors keep their titles, nodes and connections', async () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const company = data.nodes.find(
    (n) =>
      n.kind === 'company' &&
      data.edges.filter((e) => e.source === n.id || e.target === n.id).length >
        2,
  )!;
  const linked = new Set(
    data.edges
      .filter((e) => e.source === company.id || e.target === company.id)
      .flatMap((e) => [e.source, e.target]),
  );
  const base = toG6Data(data, 1200, 700, company.id);
  for (const node of base.nodes ?? [])
    node.style = { ...node.style, x: 45, y: 22 };
  const { graph, visible } = cullingGraph();
  await applyGraphReading(graph, base, data, {
    ...context,
    zoom: 0.2,
    selected: company.id,
  });
  const issues = data.nodes.filter(
    (n) =>
      n.kind === 'issue' &&
      linked.has(n.id) &&
      base.nodes?.some((node) => node.id === n.id),
  );
  expect(issues.length).toBeGreaterThan(1);
  for (const issue of issues) expect(visible(issue.id, 'label')).toBe(true);
  for (const issue of issues) expect(visible(issue.id, 'key')).toBe(true);
  for (const edge of data.edges.filter(
    (e) => e.source === company.id || e.target === company.id,
  ))
    expect(visible(edge.id, 'key')).toBe(true);
});

test('D-GRP-01 overlapping titles never fold a follow-up issue or its FOLLOWS line', async () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const follow = data.edges.find((e) => e.relationType === 'FOLLOWS')!;
  // Leave each end of the chain with one company, so neither is protected as a shared issue.
  const kept = new Set<string>();
  data.edges = data.edges.filter((e) => {
    const end = [follow.source, follow.target].find(
      (id) =>
        e.relationType !== 'FOLLOWS' && (e.source === id || e.target === id),
    );
    if (!end) return true;
    if (kept.has(end)) return false;
    kept.add(end);
    return true;
  });
  const base = toG6Data(data, 1200, 700);
  const { graph, visible } = cullingGraph();
  await applyGraphReading(graph, base, data, { ...context, zoom: 1 });
  for (const id of [follow.source, follow.target])
    expect(visible(id, 'key')).toBe(true);
  expect(visible(follow.id, 'key')).toBe(true);
});

test('D-GRP-01 a folded issue takes its evidence badge along and both come back', async () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const base = toG6Data(data, 1200, 700);
  const summary = graphSummaryOf(data);
  const follows = new Set(
    data.edges
      .filter((e) => e.relationType === 'FOLLOWS')
      .flatMap((e) => [e.source, e.target]),
  );
  const drawn = new Set(base.nodes?.map((n) => String(n.id)));
  const singles = data.nodes.filter(
    (n) =>
      n.kind === 'issue' &&
      drawn.has(n.id) &&
      !follows.has(n.id) &&
      summary.incident.get(n.id)?.length === 1,
  );
  // Every title overlaps (cullingGraph): put every diamond on one spot too, so only a few
  // titles find a free side and the rest fold.
  for (const node of base.nodes ?? [])
    node.style = { ...node.style, x: 45, y: 22 };
  const { graph, visible, room } = cullingGraph();
  await applyGraphReading(graph, base, data, { ...context, zoom: 1 });
  const hidden = singles.filter((n) => !visible(n.id, 'key'));
  expect(hidden.length).toBeGreaterThan(0);
  for (const n of hidden) expect(visible(n.id, 'badge-0')).toBe(false);
  // The same shapes are shown again once every title has room.
  room.overlap = false;
  await applyGraphReading(graph, base, data, { ...context, zoom: 1 });
  for (const n of hidden) {
    expect(visible(n.id, 'key')).toBe(true);
    expect(visible(n.id, 'badge-0')).toBe(true);
  }
});

test('D-GRP-01 an overlapping issue title moves to a free side of its circle', () => {
  // 2026-11-04 리뷰: 호버로 보인 사건 제목이 겹치면 사건 원의 빈 쪽(아래·왼쪽·오른쪽)으로 옮겨요.
  const top = { x: 0, y: 0, width: 100, height: 20 };
  const entry = (id: string, alternatives = true) => ({
    id,
    box: top,
    priority: 5,
    distance: 0,
    degree: 0,
    evidence: 0,
    alternatives: alternatives
      ? [
          { placement: 'top' as const, box: top },
          { placement: 'bottom' as const, box: { ...top, y: 60 } },
        ]
      : undefined,
  });
  const placements = new Map();
  const hidden = culledLabels([entry('a'), entry('b')], [], placements);
  expect([...hidden]).toEqual([]);
  expect(placements.get('a')).toBe('top');
  expect(placements.get('b')).toBe('bottom');
});

test.each([0.53, 1, 1.5])(
  'D-GRP-01 issue titles sit in a pill: radius is half of a one-line box at zoom %s',
  (zoom) => {
    const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const base = toG6Data(data, 1200, 700);
    const issue = readingStyles(base, data, { ...context, zoom }).nodes!.find(
      (node) => node.data?.kind === 'issue',
    )!.style!;
    const size = Number(issue.labelFontSize);
    const [vertical, horizontal] = issue.labelPadding as [number, number];
    const oneLine = Number(issue.labelLineHeight) + vertical * 2;
    expect(Number(issue.labelBackgroundRadius)).toBeCloseTo(oneLine / 2);
    // 둥근 끝에 글자가 닿지 않도록 양옆 여백이 위아래보다 넓다.
    expect(horizontal).toBeGreaterThan(vertical);
    expect(horizontal).toBeCloseTo(size * 0.75);
    expect(Number(issue.labelBackgroundLineWidth) * zoom).toBeCloseTo(0.667);
  },
);
