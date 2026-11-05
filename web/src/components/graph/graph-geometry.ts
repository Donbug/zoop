import type { NodeData } from '@antv/g6';
import { MIN_GRAPH_ZOOM } from './graph-zoom-range';

export type Rect = { x: number; y: number; width: number; height: number };
const glyphWidth = (char: string, size: number) =>
  char.codePointAt(0)! <= 127 ? size * 0.62 : size;
export function textWidth(text: string, size: number) {
  return Array.from(text).reduce(
    (sum, char) => sum + glyphWidth(char, size),
    0,
  );
}
export function shortTitle(text: string, size = 13, maxWidth = 180) {
  if (textWidth(text, size) <= maxWidth) return text;
  let result = '';
  for (const char of Array.from(text)) {
    if (textWidth(result + char + '…', size) > maxWidth) break;
    result += char;
  }
  return result + '…';
}

/** 화면 맞춤용 이름표 폭(화면 px). graph-readability가 이름표를 배율에 반비례(13/zoom, 줄바꿈 170/zoom)로 그려 화면에서는 크기가 일정하다. */
// D-GRP-03: keep the selected company distinguishable after LOD correction.
export function screenLabelSize(node: NodeData) {
  return node.data?.chosen ? 16 : 13;
}
const FIT_LABEL_WRAP = 170;

/**
 * 맞춤 경계: 노드 원은 지도 좌표, 이름표는 화면 px로 따로 잰다.
 * 이름표 크기가 지금 배율에 따라 바뀌므로 지도 좌표에 섞으면 맞춤을 반복할수록 더 축소될 수 있다.
 */
type FitFootprint = {
  x: number;
  y: number;
  radius: number;
  labelWidth: number;
  labelHeight: number;
  labelAbove?: boolean;
};
export function fitFootprint(node: NodeData): FitFootprint {
  const s = node.style ?? {};
  const dimensions = Array.isArray(s.size)
    ? s.size
    : [s.size ?? 8, s.size ?? 8];
  const radius = Number(dimensions[1] ?? dimensions[0]) / 2;
  const label = String(s.labelText ?? '');
  const fontSize = screenLabelSize(node);
  const oneLine = textWidth(label, fontSize);
  const lines = label ? Math.max(1, Math.ceil(oneLine / FIT_LABEL_WRAP)) : 0;
  return {
    x: Number(s.x ?? 0),
    y: Number(s.y ?? 0),
    radius: radius + 4,
    labelWidth: label ? Math.min(oneLine, FIT_LABEL_WRAP) + 24 : 0,
    labelHeight: label ? lines * fontSize * 1.5 + 8 + 10 : 0,
    labelAbove: s.labelPlacement === 'top',
  };
}

/** D-GRP-01: whole-map LOD hides issue titles; they must not shrink the mobile overview. */
export function overviewFootprint(node: NodeData) {
  return fitFootprint(
    node.data?.kind === 'issue'
      ? { ...node, style: { ...node.style, labelText: '' } }
      : node,
  );
}

/**
 * 맞춤 배율: 노드 원 범위(지도 좌표)에 이름표가 차지하는 화면 여백을 더해 화면에 들어가는 가장 큰 배율.
 * 지금 배율을 입력으로 쓰지 않아 같은 노드를 다시 맞춰도 같은 값이 나온다.
 */
export function fitZoom(
  footprints: ReturnType<typeof fitFootprint>[],
  safe: { width: number; height: number },
  maxZoom: number,
  /**
   * 'labels': center on circles plus titles (whole-map fit).
   * 'circles': keep the circles' center, as selection and neighborhood fits always did,
   * and reserve title room symmetrically around it.
   */
  centerOn: 'labels' | 'circles' = 'labels',
) {
  const circleCenter: [number, number] = [
    (Math.min(...footprints.map((f) => f.x - f.radius)) +
      Math.max(...footprints.map((f) => f.x + f.radius))) /
      2,
    (Math.min(...footprints.map((f) => f.y - f.radius)) +
      Math.max(...footprints.map((f) => f.y + f.radius))) /
      2,
  ];
  // D-GRP-01: measure each label at its own node. Reserving the widest label
  // at both outer graph edges wastes most of a narrow mobile viewport.
  const bounds = (zoom: number) => {
    let left = Infinity,
      right = -Infinity,
      top = Infinity,
      bottom = -Infinity;
    const labelScale = Math.max(1, zoom);
    for (const f of footprints) {
      const radius = f.radius * zoom;
      const halfWidth = Math.max(radius, (f.labelWidth * labelScale) / 2);
      const labelHeight = f.labelHeight * labelScale;
      left = Math.min(left, f.x * zoom - halfWidth);
      right = Math.max(right, f.x * zoom + halfWidth);
      top = Math.min(
        top,
        f.y * zoom - radius - (f.labelAbove ? labelHeight : 0),
      );
      bottom = Math.max(
        bottom,
        f.y * zoom + radius + (f.labelAbove ? 0 : labelHeight),
      );
    }
    return { left, right, top, bottom };
  };
  const occupied = (zoom: number) => {
    const b = bounds(zoom);
    if (centerOn === 'circles') {
      const [cx, cy] = [circleCenter[0] * zoom, circleCenter[1] * zoom];
      return Math.max(
        (2 * Math.max(cx - b.left, b.right - cx)) / safe.width,
        (2 * Math.max(cy - b.top, b.bottom - cy)) / safe.height,
      );
    }
    return Math.max(
      (b.right - b.left) / safe.width,
      (b.bottom - b.top) / safe.height,
    );
  };
  const fits = (zoom: number) => occupied(zoom) <= 1 + 1e-9;
  let lower = MIN_GRAPH_ZOOM,
    upper = Math.max(lower, maxZoom);
  if (fits(upper)) lower = upper;
  else {
    if (!fits(lower)) {
      // Opposite-side labels can overlap at minimum zoom, then separate enough
      // to fit before larger zooms exceed the viewport. Find a feasible point
      // in the convex occupied span before searching its upper boundary.
      let left = lower,
        right = upper;
      for (let step = 0; step < 48; step++) {
        const a = left + (right - left) / 3;
        const b = right - (right - left) / 3;
        if (occupied(a) <= occupied(b)) right = b;
        else left = a;
      }
      const feasible = (left + right) / 2;
      if (fits(feasible)) lower = feasible;
    }
    if (fits(lower))
      for (let step = 0; step < 28; step++) {
        const middle = (lower + upper) / 2;
        if (fits(middle)) lower = middle;
        else upper = middle;
      }
  }
  const zoom = lower;
  const measured = bounds(zoom);
  if (centerOn === 'circles') return { zoom, center: circleCenter };
  return {
    zoom,
    center: [
      (measured.left + measured.right) / (2 * zoom),
      (measured.top + measured.bottom) / (2 * zoom),
    ] as [number, number],
  };
}

// Conservative world-space footprints include the label background and badges.
export function nodeRect(node: NodeData): Rect {
  const s = node.style ?? {};
  // G6 normalizes scalar sizes into [width, height] after a layout.
  const dimensions = Array.isArray(s.size)
    ? s.size
    : [s.size ?? 8, s.size ?? 8];
  const radius = Number(dimensions[1] ?? dimensions[0]) / 2;
  const font = Number(s.labelFontSize ?? 13);
  const label = String(s.labelText ?? '');
  const labelHeight = label ? font * 1.5 + 8 : 0;
  const width = Math.max(
    Number(dimensions[0]) + 8,
    textWidth(label, font) + 24,
  );
  const offset = Math.abs(Number(s.labelOffsetY ?? 10));
  const above = s.labelPlacement === 'top' ? labelHeight + offset : 0;
  const below = s.labelPlacement === 'bottom' ? labelHeight + offset : 0;
  return {
    x: Number(s.x ?? 0) - width / 2,
    y: Number(s.y ?? 0) - radius - above,
    width,
    height: radius * 2 + above + below + 12,
  };
}
/**
 * D-GRP-01 (2026-11-05): the map may not be dragged into empty canvas. Some part of the
 * graph must stay in the middle of the screen: the circles' screen box has to reach the
 * central band that leaves `keep` of the width/height free on each side. An edge node
 * can still be brought to the center. Returns the screen-px move that restores this.
 */
export const PAN_KEEP = 0.25;
export function panCorrection(
  box: Rect,
  width: number,
  height: number,
  keep = PAN_KEEP,
): [number, number] {
  const axis = (start: number, size: number, screen: number) => {
    const low = screen * keep,
      high = screen * (1 - keep);
    if (start + size < low) return low - (start + size);
    if (start > high) return high - start;
    return 0;
  };
  return [axis(box.x, box.width, width), axis(box.y, box.height, height)];
}

export function intersects(a: Rect, b: Rect, gap = 0) {
  return (
    a.x < b.x + b.width + gap &&
    a.x + a.width + gap > b.x &&
    a.y < b.y + b.height + gap &&
    a.y + a.height + gap > b.y
  );
}

// Stable greedy placement, spatially indexed to avoid an all-pairs simulation.
// Unchanged inputs always yield the same positions; filters never relayout.
export function separateNodes(nodes: NodeData[]): NodeData[] {
  const cells = new Map<string, Rect[]>();
  const cellSize = 256;
  function keys(rect: Rect) {
    const result: string[] = [];
    for (
      let x = Math.floor((rect.x - 16) / cellSize);
      x <= Math.floor((rect.x + rect.width + 16) / cellSize);
      x++
    )
      for (
        let y = Math.floor((rect.y - 16) / cellSize);
        y <= Math.floor((rect.y + rect.height + 16) / cellSize);
        y++
      )
        result.push(`${x}:${y}`);
    return result;
  }
  const positions = new Map<string, NodeData>();
  // D-GRP-01: companies claim their place first and issues move around them. Placing
  // issues first pushed a busy company (삼성전자 339px) away from its own issues,
  // leaving them all on one side of it.
  const company = (node: NodeData) => (node.data?.kind === 'issue' ? 1 : 0);
  for (const node of [...nodes].sort(
    (a, b) =>
      company(a) - company(b) || String(a.id).localeCompare(String(b.id)),
  )) {
    const original = nodeRect(node);
    let rect = original;
    let step = 0;
    while (
      keys(rect).some((key) =>
        cells.get(key)?.some((other) => intersects(rect, other, 16)),
      )
    ) {
      step++;
      // Square spiral provides unbounded space even for coincident nodes.
      const ring = Math.ceil((Math.sqrt(step + 1) - 1) / 2);
      const side = ring * 2;
      const index = step - (2 * ring - 1) ** 2;
      const edge = Math.floor(index / side);
      const along = index % side;
      const [dx, dy] =
        edge === 0
          ? [ring, -ring + along]
          : edge === 1
            ? [ring - along, ring]
            : edge === 2
              ? [-ring, ring - along]
              : [-ring + along, -ring];
      rect = { ...original, x: original.x + dx * 48, y: original.y + dy * 48 };
    }
    keys(rect).forEach((key) =>
      cells.set(key, [...(cells.get(key) ?? []), rect]),
    );
    positions.set(String(node.id), {
      ...node,
      style: {
        ...node.style,
        x: Number(node.style?.x ?? 0) + rect.x - original.x,
        y: Number(node.style?.y ?? 0) + rect.y - original.y,
      },
    });
  }
  return nodes.map((node) => positions.get(String(node.id))!);
}

// Largest free axis-aligned viewport rectangle around measured UI overlays.
export function freeViewport(
  width: number,
  height: number,
  obstacles: Rect[],
): Rect {
  const margin = 20;
  const bounds = {
    x: margin,
    y: margin,
    width: Math.max(1, width - margin * 2),
    height: Math.max(1, height - margin * 2),
  };
  const clipped = obstacles
    .map((o) => ({
      x: Math.max(margin, o.x - 12),
      y: Math.max(margin, o.y - 12),
      width:
        Math.min(width - margin, o.x + o.width + 12) -
        Math.max(margin, o.x - 12),
      height:
        Math.min(height - margin, o.y + o.height + 12) -
        Math.max(margin, o.y - 12),
    }))
    .filter((o) => o.width > 0 && o.height > 0);
  const xs = [
    ...new Set([
      bounds.x,
      bounds.x + bounds.width,
      ...clipped.flatMap((o) => [o.x, o.x + o.width]),
    ]),
  ].sort((a, b) => a - b);
  const ys = [
    ...new Set([
      bounds.y,
      bounds.y + bounds.height,
      ...clipped.flatMap((o) => [o.y, o.y + o.height]),
    ]),
  ].sort((a, b) => a - b);
  let best: Rect = { ...bounds, width: 0, height: 0 };
  for (let l = 0; l < xs.length; l++)
    for (let r = l + 1; r < xs.length; r++)
      for (let t = 0; t < ys.length; t++)
        for (let b = t + 1; b < ys.length; b++) {
          const candidate = {
            x: xs[l],
            y: ys[t],
            width: xs[r] - xs[l],
            height: ys[b] - ys[t],
          };
          if (
            candidate.width * candidate.height > best.width * best.height &&
            !clipped.some((o) => intersects(candidate, o))
          )
            best = candidate;
        }
  return best;
}
