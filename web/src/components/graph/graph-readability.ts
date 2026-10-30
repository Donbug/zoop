import type { Graph, GraphData } from '@antv/g6';
import type { GraphResponse } from '@/types/map/graph';
import { intersects, screenLabelSize, type Rect } from './graph-geometry';

export type ReadingContext = {
  zoom: number;
  anchor: string | null;
  edge: string | null;
  focus: string | null;
  path: ReadonlySet<string>;
};
export type LabelCandidate = {
  id: string;
  box: Rect;
  priority: number;
  distance: number;
  degree: number;
  evidence: number;
};

// D-GRP-01/01b · R1–R3. Only labels are culled; data, badges and positions stay intact.
export function culledLabels(
  candidates: LabelCandidate[],
  bodies: { id: string; box: Rect }[],
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
    if (
      item.priority > 0 &&
      keys(item.box).some((key) =>
        cells
          .get(key)
          ?.some(
            (other) =>
              other.id !== item.id && intersects(item.box, other.box, 2),
          ),
      )
    )
      hidden.add(item.id);
    else add(item);
  }
  return hidden;
}

/** Screen text stays >=13px; §4.4 keeps full summaries and wraps instead of inventing shorter wording. */
export function readingStyles(
  base: GraphData,
  data: GraphResponse,
  context: ReadingContext,
): GraphData {
  const zoom = Math.max(0.01, context.zoom);
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const related = new Set(context.anchor ? [context.anchor] : []);
  for (const e of base.edges ?? [])
    if (e.source === context.anchor || e.target === context.anchor) {
      related.add(String(e.source));
      related.add(String(e.target));
    }
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
      return {
        ...node,
        style: {
          ...node.style,
          labelText: source?.label ?? node.style?.labelText,
          // D-GRP-01: 기업·사건 이름은 배율로 숨기지 않고 같은 겹침 처리 기준을 사용해요.
          labelVisibility:
            node.style?.visibility !== 'hidden' ? 'visible' : 'hidden',
          labelFontSize: size,
          labelWordWrap: true,
          labelWordWrapWidth: 170 / zoom,
          labelMaxWidth: 170 / zoom,
          labelMaxLines: Math.max(1, (source?.label ?? '').length),
          badges:
            source?.kind === 'issue' &&
            source.evidenceCount !== null &&
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

/** Label styles last pushed per graph; a new base (setData) starts over. */
const appliedLabels = new WeakMap<
  Graph,
  { base: GraphData; styles: Map<string, string> }
>();

/** Keys readingStyles derives from zoom; other label styles (colours) still come from the new data. */
const READING_KEYS = new Set([
  'labelText',
  'labelVisibility',
  'labelFontSize',
  'labelWordWrap',
  'labelWordWrapWidth',
  'labelMaxWidth',
  'labelMaxLines',
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
    applied = { base, styles: new Map() };
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
  const related = new Set<string>();
  const degrees = new Map<string, number>();
  for (const edge of base.edges ?? []) {
    for (const id of [String(edge.source), String(edge.target)])
      degrees.set(id, (degrees.get(id) ?? 0) + 1);
    if (edge.source === context.anchor || edge.target === context.anchor) {
      related.add(String(edge.source));
      related.add(String(edge.target));
    }
  }
  const candidates: LabelCandidate[] = [],
    bodies: { id: string; box: Rect }[] = [];
  const labels = new Map<string, Shape>();
  const anchor = base.nodes?.find(
    (n) => n.id === context.anchor || n.id === context.focus,
  );
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
    if (node.style?.labelVisibility === 'hidden') {
      showLabel(shape?.getShape('label'), false);
      continue;
    }
    const label = shape?.getShape('label');
    prepareLabel(label, node.style);
    showLabel(label, true);
    const box = screenBox(label);
    if (!label || !box) continue;
    const emphasis = related.has(id) || context.path.has(id);
    const priority =
      id === context.anchor || id === context.focus
        ? 0
        : source?.kind === 'company'
          ? emphasis
            ? 1
            : source.holding || source.watch
              ? 2
              : 3
          : id === '__isolated__'
            ? 4
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
  for (const id of culledLabels(candidates, bodies))
    showLabel(labels.get(id), false);
}
