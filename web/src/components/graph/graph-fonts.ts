import type { GraphData } from '@antv/g6';

/** Web fonts the G6 canvas draws with (graph-model.ts). */
export const GRAPH_FONTS = [
  'Pretendard Variable',
  'Wanted Sans Variable',
  'SUIT Variable',
];
/** Never hold the map back longer than this; a late font falls back to the stack. */
const FONT_WAIT_MS = 3000;

/**
 * Every character the canvas may draw: labels, logo initials and badges.
 * `labels` adds text drawn later, e.g. full issue titles that readingStyles
 * swaps in for the shortened labelText.
 */
export function graphText(data: GraphData, labels: readonly string[] = []) {
  const text = new Set('0123456789');
  const add = (value: unknown) => {
    if (typeof value === 'string') for (const char of value) text.add(char);
  };
  for (const node of data.nodes ?? []) {
    add(node.style?.labelText);
    add(node.style?.iconText);
    const badges = node.style?.badges;
    if (Array.isArray(badges))
      for (const badge of badges) add((badge as { text?: unknown }).text);
  }
  for (const edge of data.edges ?? []) add(edge.style?.labelText);
  for (const label of labels) add(label);
  return [...text].join('');
}

/**
 * Canvas text is drawn once with whatever font is ready then. document.fonts.ready
 * only covers fonts the page already uses, and the split fonts load per
 * unicode-range, so request every graph font for the text the map will draw.
 */
export async function loadGraphFonts(text: string) {
  const fonts = typeof document === 'undefined' ? undefined : document.fonts;
  if (!fonts) return;
  if (typeof fonts.load !== 'function') {
    await fonts.ready;
    return;
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  await Promise.race([
    Promise.all(
      GRAPH_FONTS.map((family) => fonts.load(`16px "${family}"`, text)),
    ).catch(() => undefined),
    new Promise((resolve) => {
      timer = setTimeout(resolve, FONT_WAIT_MS);
    }),
  ]);
  clearTimeout(timer);
}
