import { beforeEach, expect, it } from 'vitest';
import {
  emptyView,
  isolatedIssues,
  MAP_LAYOUT_REVISION,
  readModeEntry,
  saveModeEntry,
  restoreTargets,
} from '@/components/graph/graph-view';
import { createMockGraph } from '@/mocks/graph/response';
beforeEach(() => sessionStorage.clear());
it('keeps mode and member viewport memories separate and rejects malformed cameras', () => {
  const entry = {
    url: '/?mode=all&select=node%3ANASDAQ%3ANVDA',
    view: {
      hidden: ['FOLLOWS' as const],
      camera: {
        zoom: 1.5,
        position: [30, 40] as [number, number],
        size: [1200, 700] as [number, number],
        layout: MAP_LAYOUT_REVISION,
      },
    },
  };
  saveModeEntry('member-a', 'all', entry);
  expect(readModeEntry('member-a', 'all')).toEqual(entry);
  expect(readModeEntry('member-a', 'personal')).toBeNull();
  expect(readModeEntry('member-b', 'all')).toBeNull();
  sessionStorage.setItem(
    'zoop.graph.view:member-a:all',
    JSON.stringify({
      ...entry,
      view: { ...entry.view, camera: { zoom: Infinity, position: [1] } },
    }),
  );
  expect(readModeEntry('member-a', 'all')?.view.camera).toBeUndefined();
});
it('D-GRP-01 drops cameras from before the current layout but keeps the address and display settings', () => {
  // Reviews #321/#330: relationship compaction and larger text changed node coordinates. Replaying an older
  // camera on the new coordinates can push every node off screen on first open.
  for (const layout of [undefined, 1, 2, 3]) {
    sessionStorage.setItem(
      'zoop.graph.view:member-a:all',
      JSON.stringify({
        url: '/?mode=all&select=node%3ANAVER',
        view: {
          hidden: ['SHARES_ISSUE'],
          camera: {
            zoom: 1,
            position: [-940, 0],
            size: [1245, 705],
            ...(layout === undefined ? {} : { layout }),
          },
        },
      }),
    );
    const entry = readModeEntry('member-a', 'all');
    expect(entry?.url).toBe('/?mode=all&select=node%3ANAVER');
    expect(entry?.view.hidden).toEqual(['SHARES_ISSUE']);
    expect(entry?.view.camera).toBeUndefined();
  }
});
it('restores real selection, focus and path only, and reports removed targets', () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const saved = {
    url: '/?mode=all&select=node%3ANASDAQ%3ANVDA&focus=NASDAQ%3ANVDA&hops=2&path=NASDAQ%3ANVDA%2CKRX%3A005930&impact=missing%2Cissue',
    view: emptyView(),
  };
  const result = restoreTargets(saved, graph);
  expect(result.changes.select).toBe('node:NASDAQ:NVDA');
  expect(result.changes.focus).toBe('NASDAQ:NVDA');
  expect(result.changes.hops).toBe('2');
  expect(result.changes.path).toBe('NASDAQ:NVDA,KRX:005930');
  expect(result.changes.impact).toBeNull();
  expect(result.dropped).toBe(true);
});
it('an isolated bundle contains only actual issue nodes with no incident edges', () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const isolated = isolatedIssues(graph);
  expect(isolated.length).toBeGreaterThan(0);
  expect(
    isolated.every(
      (node) =>
        node.kind === 'issue' &&
        !graph.edges.some(
          (edge) => edge.source === node.id || edge.target === node.id,
        ),
    ),
  ).toBe(true);
});
