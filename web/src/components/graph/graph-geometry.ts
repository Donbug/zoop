import type { NodeData } from '@antv/g6';

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
export function fitFootprint(node: NodeData) {
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
  };
}

/**
 * 맞춤 배율: 노드 원 범위(지도 좌표)에 이름표가 차지하는 화면 여백을 더해 화면에 들어가는 가장 큰 배율.
 * 지금 배율을 입력으로 쓰지 않아 같은 노드를 다시 맞춰도 같은 값이 나온다.
 */
export function fitZoom(
  footprints: ReturnType<typeof fitFootprint>[],
  safe: { width: number; height: number },
  maxZoom: number,
) {
  const left = Math.min(...footprints.map((f) => f.x - f.radius)),
    right = Math.max(...footprints.map((f) => f.x + f.radius)),
    top = Math.min(...footprints.map((f) => f.y - f.radius)),
    bottom = Math.max(...footprints.map((f) => f.y + f.radius));
  const labelWidth = Math.max(...footprints.map((f) => f.labelWidth));
  const labelHeight = Math.max(...footprints.map((f) => f.labelHeight));
  const solve = (scale: number) =>
    Math.max(
      0.01,
      Math.min(
        maxZoom,
        Math.max(1, safe.width - labelWidth * scale) /
          Math.max(1, right - left),
        Math.max(1, safe.height - labelHeight * scale) /
          Math.max(1, bottom - top),
      ),
    );
  // 배율 1 이상에서는 이름표가 기본 크기(13)로 함께 커지므로 그만큼 한 번 더 여백을 잡는다.
  const first = solve(1);
  const zoom = first > 1 ? solve(first) : first;
  return {
    zoom,
    center: [(left + right) / 2, (top + bottom) / 2] as [number, number],
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
  for (const node of [...nodes].sort((a, b) =>
    String(a.id).localeCompare(String(b.id)),
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
