import { beforeEach, expect, it } from 'vitest';
import {
  emptyView,
  isolatedIssues,
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
      flow: true,
      camera: { zoom: 1.5, position: [30, 40] as [number, number] },
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
