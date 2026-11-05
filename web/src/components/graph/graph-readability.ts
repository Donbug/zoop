import type { Graph, GraphData } from '@antv/g6';
import type { GraphResponse } from '@/types/map/graph';
import { intersects, screenLabelSize, type Rect } from './graph-geometry';
import { MIN_GRAPH_ZOOM } from './graph-zoom-range';
import { issuePillPadding, issuePillRadius } from './graph-model';

/** Below this zoom issue titles are clipped to two lines (D-GRP-01 overview). */
export const OVERVIEW_ZOOM = 0.45;
/** Zooming in this much past the whole-graph fit brings issue titles back. */
const WHOLE_FIT_MARGIN = 1.2;

export type ReadingContext = {
  zoom: number;
  anchor: string | null;
  /** Clicked node: its connected titles stay while another node is hovered, until deselected. */
  selected?: string | null;
  edge: string | null;
  focus: string | null;
  path: ReadonlySet<string>;
  /** Elements kept bright while a selection dims the rest of the map (null: nothing dimmed). */
  bright?: ReadonlySet<string> | null;
  /** Zoom that fits the whole visible graph. Issue titles stay hidden up to just above it. */
  wholeFitZoom?: number;
};
export type LabelCandidate = {
  id: string;
  box: Rect;
  priority: number;
  distance: number;
  degree: number;
  evidence: number;
  /** Never culled: titles connected to the hovered or selected node (D-GRP-01, 2026-11-04). */
  keep?: boolean;
  /** Other sides the title may move to when its own box overlaps, in order of preference. */
  alternatives?: { placement: LabelPlacement; box: Rect }[];
};
export type LabelPlacement = 'top' | 'bottom' | 'left' | 'right';

/** The hovered/selected nodes and every node one edge away from them. */
function anchorNeighbors(base: GraphData, context: ReadingContext) {
  const anchors = new Set(
    [context.anchor, context.selected].filter((id): id is string => !!id),
  );
  const related = new Set(anchors);
  for (const e of base.edges ?? [])
    if (anchors.has(String(e.source)) || anchors.has(String(e.target))) {
      related.add(String(e.source));
      related.add(String(e.target));
    }
  return related;
}

/** Spots further from the circle: up from the top, down from the bottom, up or down beside. */
const SLIDE_STEPS = 4;
function slideSpots(options: { placement: LabelPlacement; box: Rect }[]) {
  const spots: { placement: LabelPlacement; box: Rect; shift: number }[] = [];
  for (let step = 1; step <= SLIDE_STEPS; step++)
    for (const option of options) {
      const distance = step * (option.box.height + 4);
      const directions =
        option.placement === 'top'
          ? [-1]
          : option.placement === 'bottom'
            ? [1]
            : [-1, 1];
      for (const direction of directions)
        spots.push({
          placement: option.placement,
          shift: direction * distance,
          box: { ...option.box, y: option.box.y + direction * distance },
        });
    }
  return spots;
}

// D-GRP-01/01b · R1–R3. Only labels are culled; data, badges and positions stay intact.
export function culledLabels(
  candidates: LabelCandidate[],
  bodies: { id: string; box: Rect }[],
  /** Filled with the side chosen for each title that has alternatives. */
  placements?: Map<string, LabelPlacement>,
  /** Filled with the extra screen-px slide of kept titles that found no free side. */
  shifts?: Map<string, number>,
) {
  const cells = new Map<string, { id: string; box: Rect }[]>();
  const keys = (r: Rect) => {
    const result: string[] = [];
    for (
      let x = Math.floor((r.x - 2) / 96);
      x <= Math.floor((r.x + r.width + 2) / 96);
      x++
    )
      for (
        let y = Math.floor((r.y - 2) / 96);
        y <= Math.floor((r.y + r.height + 2) / 96);
        y++
      )
        result.push(`${x}:${y}`);
    return result;
  };
  const add = (entry: { id: string; box: Rect }) =>
    keys(entry.box).forEach((key) =>
      cells.set(key, [...(cells.get(key) ?? []), entry]),
    );
  bodies.forEach(add);
  const hidden = new Set<string>();
  for (const item of [...candidates].sort(
    (a, b) =>
      a.priority - b.priority ||
      a.distance - b.distance ||
      b.degree - a.degree ||
      b.evidence - a.evidence ||
      a.id.localeCompare(b.id),
  )) {
    const free = (box: Rect) =>
      !keys(box).some((key) =>
        cells
          .get(key)
          ?.some(
            (other) => other.id !== item.id && intersects(box, other.box, 2),
          ),
      );
    if (item.priority === 0) {
      add(item);
      continue;
    }
    // D-GRP-01 (2026-11-04 review): an overlapping issue title first tries the other sides of
    // its circle, so titles shown on hover sit side by side instead of on top of each other.
    const options = item.alternatives ?? [];
    const fit = options.find((option) => free(option.box));
    shifts?.delete(item.id);
    if (fit) {
      placements?.set(item.id, fit.placement);
      add({ id: item.id, box: fit.box });
      continue;
    }
    // D-GRP-01 (2026-11-05): connected titles always stay (keep). When every side of the
    // circle is taken, slide the title further out, one title height at a time, until it
    // lands on free space, so kept titles sit apart instead of printing over one another.
    const slid = item.keep
      ? slideSpots(options).find((spot) => free(spot.box))
      : undefined;
    if (slid) {
      placements?.set(item.id, slid.placement);
      shifts?.set(item.id, slid.shift);
      add({ id: item.id, box: slid.box });
      continue;
    }
    // Nothing fits: the title goes back to its first side (shown anyway when kept).
    const box = options[0]?.box ?? item.box;
    if (options.length) placements?.set(item.id, options[0].placement);
    if (item.keep || free(box)) add({ id: item.id, box });
    else hidden.add(item.id);
  }
  return hidden;
}

/** Screen text stays >=13px; §4.4 keeps full summaries and wraps instead of inventing shorter wording. */
export function readingStyles(
  base: GraphData,
  data: GraphResponse,
  context: ReadingContext,
): GraphData {
  const zoom = Math.max(MIN_GRAPH_ZOOM, context.zoom);
  // D-GRP-01 (2026-11-04 review): the whole-graph fit shows only issue circles, even when a compact
  // map fits above OVERVIEW_ZOOM. Titles come back once the user zooms in past the fit.
  const overviewZoom = Math.max(
    OVERVIEW_ZOOM,
    (context.wholeFitZoom ?? 0) * WHOLE_FIT_MARGIN,
  );
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const related = anchorNeighbors(base, context);
  return {
    nodes: base.nodes?.map((node) => {
      const source = byId.get(String(node.id));
      const emphasized =
        node.id === context.anchor ||
        node.id === context.focus ||
        context.path.has(String(node.id)) ||
        related.has(String(node.id));
      const size = Math.max(
        Number(node.style?.labelFontSize ?? 13),
        screenLabelSize(node) / zoom,
      );
      // D-GRP-01 (2026-11-04 review): zoomed out, an issue is only a circle that says
      // "there is an issue here"; its title and count come back on zoom, hover or selection.
      const overview =
        source?.kind === 'issue' && zoom < overviewZoom && !emphasized;
      return {
        ...node,
        style: {
          ...node.style,
          labelText: source?.label ?? node.style?.labelText,
          // D-GRP-01: 기업·사건 이름은 배율로 숨기지 않고 같은 겹침 처리 기준을 사용해요.
          labelVisibility:
            node.style?.visibility !== 'hidden' && !overview
              ? 'visible'
              : 'hidden',
          labelFontSize: size,
          // 배율에 맞춘 글자 크기로 알약 모양 여백과 반지름을 다시 잰다.
          ...(source?.kind === 'issue'
            ? {
                labelPadding: issuePillPadding(size),
                labelBackgroundRadius: issuePillRadius(size),
                // 테두리도 화면 기준 0.667px로 유지해야 줄여 볼 때도 둥근 상자가 보인다.
                labelBackgroundLineWidth: 0.667 / zoom,
              }
            : {}),
          // D-GRP-01: G keeps a fixed 16px line height; it must grow with the zoom-corrected font
          // or wrapped lines overlap and the culling below measures a box shorter than the text.
          labelLineHeight: size * 1.3,
          labelWordWrap: true,
          labelWordWrapWidth: 170 / zoom,
          labelTextOverflow: 'ellipsis',
          labelMaxWidth: 170 / zoom,
          // D-GRP-01: the zoomed-out overview shows two lines of each issue title; zooming in,
          // hovering or selecting brings back the whole title.
          labelMaxLines:
            source?.kind === 'issue' && zoom < overviewZoom && !emphasized
              ? 2
              : Math.max(1, (source?.label ?? '').length),
          badges:
            source?.kind === 'issue' &&
            source.evidenceCount !== null &&
            !overview &&
            (zoom >= 0.55 || emphasized)
              ? [
                  {
                    text: String(source.evidenceCount),
                    placement: 'right-top',
                    offsetX: 8 / zoom,
                    offsetY: -4 / zoom,
                    fontSize: 13 / zoom,
                    fill: node.style?.labelBackgroundFill ?? node.style?.fill,
                    backgroundFill: node.style?.labelFill,
                    padding: [2 / zoom, 4 / zoom],
                  },
                ]
              : Number(node.data?.folded) > 0
                ? [
                    ...(node.style?.badges ?? []),
                    // D-GRP-01: issues folded into the company until it is selected.
                    {
                      text: `+${Number(node.data?.folded)}`,
                      placement: 'right-top',
                      offsetX: 4 / zoom,
                      offsetY: -2 / zoom,
                      fontSize: 13 / zoom,
                      fontWeight: 700,
                      fill: node.style?.labelBackgroundFill,
                      backgroundFill: node.style?.labelFill,
                      padding: [2 / zoom, 5 / zoom],
                    },
                  ]
                : node.style?.badges,
        },
      };
    }),
    // D-GRP-01: 사건 이름은 노드에만 표시해요. 호버·선택·확대 뒤에도 선의 태그는 복원하지 않아요.
    edges: base.edges?.map((edge) => ({
      ...edge,
      style: {
        ...edge.style,
        labelText: '',
        labelVisibility: 'hidden',
      },
    })),
  };
}

/** G6 label style for an issue title on one side of its circle (top is the default). */
/** shift: extra vertical slide in graph units (screen px / zoom), so it scales with the circle. */
const placementStyle = (side: LabelPlacement, shift = 0) => ({
  labelPlacement: side,
  labelOffsetY: (side === 'top' ? -5 : side === 'bottom' ? 5 : 0) + shift,
  labelOffsetX: side === 'left' ? -5 : side === 'right' ? 5 : 0,
});

/** Label styles last pushed per graph; a new base (setData) starts over. */
const appliedLabels = new WeakMap<
  Graph,
  {
    base: GraphData;
    styles: Map<string, string>;
    /** Issue titles moved off their default top side to avoid an overlap. */
    placements: Map<string, LabelPlacement>;
    /** Extra slide (graph units) of kept titles that found no free side. */
    shifts: Map<string, number>;
  }
>();

/** Keys readingStyles derives from zoom; other label styles (colours) still come from the new data. */
const READING_KEYS = new Set([
  'labelText',
  'labelVisibility',
  'labelFontSize',
  'labelPadding',
  'labelBackgroundRadius',
  'labelBackgroundLineWidth',
  'labelWordWrap',
  'labelWordWrapWidth',
  'labelMaxWidth',
  'labelMaxLines',
  'labelLineHeight',
  'badges',
]);

/**
 * Carry the label styles the reading pass applied into new graph data, and fill
 * keys the new data leaves out (G6's zIndex, sourceNode/targetNode, ...) from the
 * model. G6 updateData keeps omitted keys anyway, but its diff counts them as
 * changes: setData would redraw every element, then the reading pass again.
 * An element whose own label input changed (text, badges, ...) keeps the new
 * data's values instead, so it never shows the old label until the next reading.
 */
export function keepAppliedStyles(graph: Graph, data: GraphData): GraphData {
  if (
    typeof graph.getNodeData !== 'function' ||
    typeof graph.getEdgeData !== 'function'
  )
    return data;
  const current = new Map(
    [...graph.getNodeData(), ...graph.getEdgeData()].map((item) => [
      String(item.id),
      item.style ?? {},
    ]),
  );
  const read = appliedLabels.get(graph)?.base;
  const before = new Map(
    [...(read?.nodes ?? []), ...(read?.edges ?? [])].map((item) => [
      String(item.id),
      item.style ?? {},
    ]),
  );
  const keep = <T extends { id?: unknown; style?: Record<string, unknown> }>(
    item: T,
  ): T => {
    const model = current.get(String(item.id));
    if (!model) return item;
    const style: Record<string, unknown> = { ...item.style };
    const last = before.get(String(item.id));
    const sameLabel =
      !last ||
      [...READING_KEYS].every(
        (key) => JSON.stringify(last[key]) === JSON.stringify(style[key]),
      );
    for (const [key, value] of Object.entries(model))
      if ((sameLabel && READING_KEYS.has(key)) || !(key in style))
        style[key] = value;
    return { ...item, style };
  };
  return {
    ...data,
    nodes: data.nodes?.map(keep),
    edges: data.edges?.map(keep),
  };
}

// Public G6 canvas/display-object APIs give actual label bounds (font/wrap/padding/rotation).
export async function applyGraphReading(
  graph: Graph,
  base: GraphData,
  data: GraphResponse,
  context: ReadingContext,
) {
  if (graph.destroyed || typeof graph.getCanvas !== 'function') return;
  const styles = readingStyles(base, data, context);
  // Reading work can run after a drag. Never replay cached geometry or relation
  // presentation into the current model; only labels and badges belong here.
  const labelStyle = (
    style: Record<string, unknown> | undefined,
    badges = false,
  ) =>
    Object.fromEntries(
      Object.entries(style ?? {}).filter(
        ([key]) => key.startsWith('label') || (badges && key === 'badges'),
      ),
    );
  // Hover keeps the zoom, so most label styles are unchanged: only push and redraw the changed ones.
  let applied = appliedLabels.get(graph);
  if (!applied) {
    applied = {
      base,
      styles: new Map(),
      placements: new Map(),
      shifts: new Map(),
    };
    appliedLabels.set(graph, applied);
  } else if (applied.base !== base) {
    // setData keeps applied label styles on elements that stay (keepAppliedStyles);
    // elements that left the data start from their defaults if they come back.
    const after = new Set(
      [...(base.nodes ?? []), ...(base.edges ?? [])].map((item) =>
        String(item.id),
      ),
    );
    for (const id of applied.styles.keys())
      if (!after.has(id)) applied.styles.delete(id);
    applied.base = base;
  }
  const { styles: previous } = applied;
  const changed = (
    items: { id?: unknown; style?: Record<string, unknown> }[] | undefined,
    badges = false,
  ) =>
    (items ?? []).flatMap((item) => {
      const id = String(item.id);
      const style = labelStyle(item.style, badges);
      const key = JSON.stringify(style);
      if (previous.get(id) === key) return [];
      previous.set(id, key);
      return [{ id, style }];
    });
  const { placements, shifts } = applied;
  for (const node of styles.nodes ?? []) {
    const side = placements.get(String(node.id));
    const shift = shifts.get(String(node.id)) ?? 0;
    if (side || shift)
      node.style = { ...node.style, ...placementStyle(side ?? 'top', shift) };
  }
  const nodeUpdates = changed(styles.nodes, true);
  const edgeUpdates = changed(styles.edges);
  if (nodeUpdates.length) graph.updateNodeData(nodeUpdates);
  if (edgeUpdates.length) graph.updateEdgeData(edgeUpdates);
  if (nodeUpdates.length || edgeUpdates.length) await graph.draw();
  if (graph.destroyed) return;
  const document = graph.getCanvas().document;
  type Shape = {
    getRenderBounds: () => { min: number[]; max: number[] };
    attr: (key: string, value: string) => void;
    style?: {
      visibility?: string;
      fontSize?: number;
      wordWrapWidth?: number;
      maxLines?: number;
    };
    update?: (style: Record<string, unknown>) => void;
    forEach?: (visit: (shape: Shape) => void) => void;
  };
  // G6 disables CSS inheritance: visibility must reach the label's text/background.
  const showLabel = (shape: Shape | undefined, visible: boolean) => {
    if (!shape) return;
    const apply = (child: Shape) => {
      const visibility = visible ? 'visible' : 'hidden';
      if (child.style) child.style.visibility = visibility;
      else child.attr('visibility', visibility);
    };
    apply(shape);
    shape.forEach?.(apply);
  };
  // G6 state redraws can restore the Label defaults even after updateNodeData.
  // Apply the same reading style to the public rendered Label before measuring.
  const prepareLabel = (
    shape: Shape | undefined,
    style: Record<string, unknown> | undefined,
  ) => {
    if (!shape?.update || !style) return;
    shape.update({
      fontSize: style.labelFontSize,
      wordWrapWidth: style.labelWordWrapWidth,
      maxLines: style.labelMaxLines,
      lineHeight: style.labelLineHeight,
    });
  };
  type ElementShape = { getShape: (name: string) => Shape | undefined };
  // G's getElementById walks the whole scene; collect every element in one walk instead.
  const wanted = new Set([
    ...(styles.nodes ?? []).map((node) => String(node.id)),
    ...(styles.edges ?? []).map((edge) => String(edge.id)),
  ]);
  const elements = new Map<string, ElementShape>();
  type SceneNode = { id?: string; childNodes?: SceneNode[] };
  const collect = (scene: SceneNode) => {
    if (scene.id && wanted.has(scene.id)) {
      elements.set(scene.id, scene as unknown as ElementShape);
      return;
    }
    scene.childNodes?.forEach(collect);
  };
  const root = document.documentElement as unknown as SceneNode | undefined;
  if (root) collect(root);
  const element = (id: string) =>
    elements.get(id) ??
    (document.getElementById(id) as unknown as ElementShape | null);
  const screenBox = (shape: Shape | undefined): Rect | null => {
    if (!shape) return null;
    const bounds = shape.getRenderBounds();
    const a = graph.getViewportByCanvas([bounds.min[0], bounds.min[1]]),
      b = graph.getViewportByCanvas([bounds.max[0], bounds.max[1]]);
    if (![...a, ...b].every(Number.isFinite)) return null;
    return {
      x: Math.min(a[0], b[0]),
      y: Math.min(a[1], b[1]),
      width: Math.abs(b[0] - a[0]),
      height: Math.abs(b[1] - a[1]),
    };
  };
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const related = anchorNeighbors(base, context);
  const degrees = new Map<string, number>();
  // Companies each issue touches on this map: shared issues always keep their circle and lines.
  const companies = new Map<string, Set<string>>();
  for (const edge of base.edges ?? []) {
    for (const id of [String(edge.source), String(edge.target)])
      degrees.set(id, (degrees.get(id) ?? 0) + 1);
    const [a, b] = [
      byId.get(String(edge.source)),
      byId.get(String(edge.target)),
    ];
    const issue = a?.kind === 'issue' ? a : b?.kind === 'issue' ? b : null;
    const company =
      a?.kind === 'company' ? a : b?.kind === 'company' ? b : null;
    if (issue && company)
      companies.set(
        issue.id,
        (companies.get(issue.id) ?? new Set()).add(company.id),
      );
  }
  const candidates: LabelCandidate[] = [],
    bodies: { id: string; box: Rect }[] = [];
  const labels = new Map<string, Shape>();
  const anchor = base.nodes?.find(
    (n) => n.id === context.anchor || n.id === context.focus,
  );
  // Screen boxes of an issue title on each side of its circle; the side it sits on now
  // keeps its measured box. Top first, then below, then beside (the count badge is top-right).
  const sides = (
    node: NonNullable<GraphData['nodes']>[number],
    box: Rect,
  ): { placement: LabelPlacement; box: Rect }[] => {
    const [cx, cy] = graph.getViewportByCanvas([
      Number(node.style?.x),
      Number(node.style?.y),
    ]);
    if (!Number.isFinite(cx) || !Number.isFinite(cy)) return [];
    const zoom = context.zoom;
    const half = (Number(node.style?.size ?? 48) / 2) * zoom;
    const gap = 5 * zoom;
    const { width, height } = box;
    const current = String(node.style?.labelPlacement ?? 'top');
    const options: { placement: LabelPlacement; box: Rect }[] = [
      {
        placement: 'top',
        box: { x: cx - width / 2, y: cy - half - gap - height, width, height },
      },
      {
        placement: 'bottom',
        box: { x: cx - width / 2, y: cy + half + gap, width, height },
      },
      {
        placement: 'left',
        box: { x: cx - half - gap - width, y: cy - height / 2, width, height },
      },
      {
        placement: 'right',
        box: { x: cx + half + gap, y: cy - height / 2, width, height },
      },
    ];
    // A slid title's measured box is off its side; use the computed side box instead.
    const slid = shifts.has(String(node.id));
    return options.map((option) =>
      option.placement === current && !slid ? { ...option, box } : option,
    );
  };
  const anchorPoint = anchor
    ? graph.getViewportByCanvas([
        Number(anchor.style?.x),
        Number(anchor.style?.y),
      ])
    : null;
  for (const node of styles.nodes ?? []) {
    if (node.style?.visibility === 'hidden') continue;
    const id = String(node.id),
      source = byId.get(id),
      shape = element(id);
    const body =
      source?.kind !== 'issue' ? screenBox(shape?.getShape('key')) : null;
    if (body) bodies.push({ id, box: body });
    // D-GRP-01 (2026-11-04 review): behind a selection, unrelated issues stay faint
    // circles without a title or count, so only the selection's titles compete for room.
    const faded =
      source?.kind === 'issue' && context.bright && !context.bright.has(id);
    if (node.style?.labelVisibility === 'hidden' || faded) {
      showLabel(shape?.getShape('label'), false);
      continue;
    }
    const label = shape?.getShape('label');
    prepareLabel(label, node.style);
    showLabel(label, true);
    const box = screenBox(label);
    if (!label || !box) continue;
    const emphasis = related.has(id) || context.path.has(id);
    const shared =
      source?.kind === 'issue' && (companies.get(id)?.size ?? 0) > 1;
    const priority =
      id === context.anchor || id === context.selected || id === context.focus
        ? 0
        : source?.kind === 'company'
          ? emphasis
            ? 1
            : source.holding || source.watch
              ? 2
              : 3
          : id === '__isolated__'
            ? 4
            : // Shared issue titles win over single-company ones but still yield to
              // each other, or several titles print on top of one another when zoomed out.
              shared
              ? 4.5
              : emphasis
                ? 5
                : 6;
    candidates.push({
      id,
      box,
      priority,
      distance: anchorPoint
        ? Math.hypot(box.x - anchorPoint[0], box.y - anchorPoint[1])
        : 0,
      degree: degrees.get(id) ?? 0,
      evidence: source?.evidenceCount ?? 0,
      // D-GRP-01 (2026-11-04 review): titles of issues connected to the hovered or clicked
      // node stay while the pointer rests there or until the selection is cleared. They
      // slide apart when they would overlap (2026-11-05). Unrelated titles yield to them.
      keep: source?.kind === 'issue' && related.has(id),
      alternatives: source?.kind === 'issue' ? sides(node, box) : undefined,
    });
    labels.set(id, label);
  }
  for (const edge of styles.edges ?? []) {
    if (edge.style?.visibility === 'hidden') continue;
    if (edge.style?.labelVisibility === 'hidden') {
      showLabel(element(String(edge.id))?.getShape('label'), false);
      continue;
    }
    const id = String(edge.id),
      label = element(id)?.getShape('label');
    prepareLabel(label, edge.style);
    showLabel(label, true);
    const box = screenBox(label);
    if (!label || !box) continue;
    candidates.push({
      id,
      box,
      priority: id === context.edge ? 0 : 7,
      distance: 0,
      degree: 0,
      evidence: 0,
    });
    labels.set(id, label);
  }
  const chosen = new Map<string, LabelPlacement>();
  const chosenShift = new Map<string, number>();
  const culled = culledLabels(candidates, bodies, chosen, chosenShift);
  for (const id of culled) showLabel(labels.get(id), false);
  // Move titles whose side changed, then hide the culled ones again (a redraw shows them).
  const moves = candidates.flatMap((candidate) => {
    if (!candidate.alternatives?.length) return [];
    const side = chosen.get(candidate.id) ?? 'top';
    const shift =
      Math.round(((chosenShift.get(candidate.id) ?? 0) / context.zoom) * 10) /
      10;
    if (
      side === (placements.get(candidate.id) ?? 'top') &&
      shift === (shifts.get(candidate.id) ?? 0)
    )
      return [];
    if (side === 'top') placements.delete(candidate.id);
    else placements.set(candidate.id, side);
    if (shift) shifts.set(candidate.id, shift);
    else shifts.delete(candidate.id);
    previous.delete(candidate.id);
    return [{ id: candidate.id, style: placementStyle(side, shift) }];
  });
  if (moves.length) {
    graph.updateNodeData(moves);
    await graph.draw();
    if (graph.destroyed) return;
    for (const id of culled) showLabel(labels.get(id), false);
  }
  // D-GRP-01 (2026-11-04 review): a single-company issue whose title does not fit is
  // folded with its line too, so no line ends at an untitled circle. Shared issues and the
  // selected company's issues keep their circle and lines (only overlapping titles wait for zoom).
  // Follow-up chains are never folded by data either (foldedIssues): keep both ends.
  const follows = new Set(
    data.edges
      .filter((e) => e.relationType === 'FOLLOWS')
      .flatMap((e) => [e.source, e.target]),
  );
  const folded = new Set(
    [...culled].filter(
      (id) =>
        byId.get(id)?.kind === 'issue' &&
        (companies.get(id)?.size ?? 0) <= 1 &&
        !follows.has(id) &&
        !related.has(id) &&
        !context.path.has(id),
    ),
  );
  for (const node of styles.nodes ?? []) {
    if (node.style?.visibility === 'hidden') continue;
    const id = String(node.id);
    if (byId.get(id)?.kind !== 'issue') continue;
    showLabel(element(id)?.getShape('key'), !folded.has(id));
    // The evidence count belongs to the title: a culled title takes its badge along.
    showLabel(
      element(id)?.getShape('badge-0'),
      !culled.has(id) && !(context.bright && !context.bright.has(id)),
    );
  }
  for (const edge of styles.edges ?? []) {
    if (edge.style?.visibility === 'hidden') continue;
    showLabel(
      element(String(edge.id))?.getShape('key'),
      !folded.has(String(edge.source)) && !folded.has(String(edge.target)),
    );
  }
}
