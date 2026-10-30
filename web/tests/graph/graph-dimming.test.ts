import { expect, test } from 'vitest';
import type { Graph } from '@antv/g6';
import {
  applyMapDimming,
  restoreMapDimming,
} from '@/components/graph/graph-dimming';

type Shape = {
  id?: string;
  parentNode?: Shape | null;
  childNodes: Shape[];
  style: Record<string, unknown>;
  appendChild: (child: Shape) => void;
};
function shape(id: string | undefined, style: Record<string, unknown>): Shape {
  const item: Shape = {
    id,
    parentNode: null,
    childNodes: [],
    style,
    appendChild: (child) => {
      child.parentNode = item;
      item.childNodes.push(child);
    },
  };
  return item;
}
function scene() {
  const root = shape(undefined, {});
  const layer = shape(undefined, {});
  root.appendChild(layer);
  const node = shape('a', { zIndex: 0 });
  const other = shape('b', { zIndex: 0 });
  const edge = shape('e', { zIndex: -1 });
  for (const item of [node, other, edge]) layer.appendChild(item);
  const graph = {
    destroyed: false,
    getCanvas: () => ({
      document: {
        documentElement: root,
        createElement: (
          _: string,
          { style }: { style: Record<string, unknown> },
        ) => shape(undefined, { ...style }),
      },
    }),
  } as unknown as Graph;
  return { graph, layer, node, other, edge };
}
const cover = (layer: Shape) => layer.childNodes.find((item) => !item.id)!;

test('D-GRP-01 dimming raises bright elements above one cover and restores them', () => {
  const { graph, layer, node, other, edge } = scene();
  const bright = new Map<string, 'node' | 'edge'>([
    ['a', 'node'],
    ['e', 'edge'],
  ]);
  applyMapDimming(graph, true, bright, '#fff');
  expect(cover(layer).style).toMatchObject({
    visibility: 'visible',
    fill: '#fff',
    zIndex: 1000,
    pointerEvents: 'none',
  });
  expect([node.style.zIndex, edge.style.zIndex, other.style.zIndex]).toEqual([
    1002, 1001, 0,
  ]);
  // G6 redraws an element at its own zIndex; the next draw raises it again.
  node.style.zIndex = 0;
  restoreMapDimming(graph);
  expect(node.style.zIndex).toBe(1002);
  applyMapDimming(graph, false, new Map(), '#000');
  expect(cover(layer).style).toMatchObject({
    visibility: 'hidden',
    fill: '#000',
  });
  expect([node.style.zIndex, edge.style.zIndex]).toEqual([0, -1]);
});

test('D-GRP-01 dimming follows replaced elements and re-attaches the cover', () => {
  const { graph, layer } = scene();
  applyMapDimming(graph, true, new Map([['a', 'node']]), '#fff');
  // setData replaced the layer contents: a new shape for "a" and no cover.
  const replaced = shape('a', { zIndex: 0 });
  for (const item of layer.childNodes) item.parentNode = null;
  layer.childNodes = [];
  layer.appendChild(replaced);
  restoreMapDimming(graph);
  expect(replaced.style.zIndex).toBe(1002);
  expect(cover(layer)).toBeTruthy();
});
