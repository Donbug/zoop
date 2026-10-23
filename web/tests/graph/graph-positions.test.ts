import { expect, test } from 'vitest';
import {
  positionKey,
  readPositions,
  restorePositions,
  savePositions,
} from '@/components/graph/graph-positions';
import { createMockGraph } from '@/mocks/graph/response';

test('D-GRP-01 coordinate memory isolates owner, scope, snapshot and arrangement', () => {
  const data = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const key = positionKey('member-a', data, 'map');
  savePositions(key, [{ id: 'a', style: { x: 450, y: 300 } }], 800, 600);
  expect(readPositions(key)).toEqual({ a: [50, 0] });
  expect(readPositions(positionKey('member-b', data, 'map'))).toEqual({});
  expect(readPositions(positionKey('member-a', data, 'flow'))).toEqual({});
  expect(
    readPositions(
      positionKey(
        'member-a',
        { ...data, metadata: { ...data.metadata, graphVersion: 'other' } },
        'map',
      ),
    ),
  ).toEqual({});
  expect(
    restorePositions(
      { nodes: [{ id: 'a', style: { x: 0, y: 0 } }] },
      readPositions(key),
      1000,
      600,
    ).nodes?.[0].style,
  ).toEqual({ x: 550, y: 300 });
  sessionStorage.setItem(key, '{"a":[null,4],"b":[2,"3"],"ok":[1,2]}');
  expect(readPositions(key)).toEqual({ ok: [1, 2] });
});

test('R4 adding a node places it near known neighbors without moving the known nodes', () => {
  const base = {
    nodes: [
      { id: 'known', style: { x: -5000, y: -5000 } },
      { id: 'new', style: { x: 6000, y: 6000 } },
    ],
    edges: [{ id: 'e', source: 'known', target: 'new' }],
  };
  const result = restorePositions(base, { known: [50, 30] }, 800, 600);
  expect(result.nodes?.[0].style).toEqual({ x: 450, y: 330 });
  expect(
    Math.hypot(
      Number(result.nodes?.[1].style?.x) - 450,
      Number(result.nodes?.[1].style?.y) - 330,
    ),
  ).toBeLessThan(400);
  expect(base.nodes[0].style).toEqual({ x: -5000, y: -5000 });
});
