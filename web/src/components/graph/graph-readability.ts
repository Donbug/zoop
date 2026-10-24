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
  const preciseTime = (id: string) => {
    const node = byId.get(id);
    return node?.timePrecision && node.timePrecision !== 'unknown'
      ? (node.eventTime ?? '')
      : '';
  };
  const recent = new Set(
    (base.edges ?? [])
      .filter(
        (e) =>
          e.style?.visibility !== 'hidden' &&
          (e.source === context.anchor || e.target === context.anchor),
      )
      .sort((a, b) => {
        const time = (e: typeof a) =>
          preciseTime(String(e.source)) || preciseTime(String(e.target));
        return (
          time(b).localeCompare(time(a)) ||
          String(a.id).localeCompare(String(b.id))
        );
      })
      .slice(0, 6)
      .map((e) => String(e.id)),
  );
  const edgeData = new Map(data.edges.map((e) => [e.id, e]));
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
          labelVisibility:
            node.style?.visibility !== 'hidden' &&
            (source?.kind !== 'issue' || zoom >= 0.55 || emphasized)
              ? 'visible'
              : 'hidden',
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
    edges: base.edges?.map((edge) => {
      const source = edgeData.get(String(edge.id));
      const emphasized =
        edge.id === context.edge ||
        context.path.has(String(edge.id)) ||
        recent.has(String(edge.id));
      const visible =
        edge.style?.visibility !== 'hidden' &&
        (emphasized ||
          (!context.anchor &&
            zoom >= 0.95 &&
            (base.edges?.length ?? 0) <= 160));
      return {
        ...edge,
        style: {
          ...edge.style,
          labelText: source?.summary ?? '',
          labelVisibility: visible ? 'visible' : 'hidden',
          labelFontSize: 13 / zoom,
          labelFontFamily: 'Pretendard Variable',
          labelFill: base.nodes?.[0]?.style?.labelFill,
          labelBackground: true,
          labelBackgroundFill: base.nodes?.[0]?.style?.labelBackgroundFill,
          labelPadding: [2 / zoom, 4 / zoom],
          labelOffsetY: -5 / zoom,
          labelAutoRotate: true,
          labelWordWrap: true,
          labelWordWrapWidth: 160 / zoom,
          labelMaxLines: Math.max(1, (source?.summary ?? '').length),
        },
      };
    }),
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
  graph.updateNodeData(
    (styles.nodes ?? []).map((n) => ({
      id: n.id,
      style: labelStyle(n.style, true),
    })),
  );
  graph.updateEdgeData(
    (styles.edges ?? []).map((e) => ({ id: e.id, style: labelStyle(e.style) })),
  );
  await graph.draw();
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
  const element = (id: string) =>
    document.getElementById(id) as unknown as ElementShape | null;
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
