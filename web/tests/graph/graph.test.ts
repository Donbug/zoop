import { describe, expect, it } from 'vitest';
import { createMockGraph } from '@/mocks/graph/response';
import { mockMember } from '@/mocks/graph/fixture';
import {
  companyNodeSize,
  graphSummary,
  toG6Data,
} from '@/components/graph/graph-model';
import { graphUrl } from '@/apis/graph/graph';

describe('WBS 6.6.21 · D-GRP-01/01b mock/API contract', () => {
  it('all is public and contains no holding/watch data', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'holdings' });
    expect(graph.nodes.every((n) => !n.holding && !n.watch)).toBe(true);
    expect(graph.metadata.personalFilter).toBeNull();
    expect(graph.nodes.filter((n) => n.kind === 'company')).toHaveLength(24);
  });
  for (const personalFilter of ['all', 'holdings', 'watchlist'] as const) {
    it(`personal ${personalFilter} uses the exact seed set without duplicate companies`, () => {
      const graph = createMockGraph({ mode: 'personal', personalFilter });
      const expected =
        personalFilter === 'all'
          ? [...new Set([...mockMember.holdings, ...mockMember.watchlist])]
          : personalFilter === 'holdings'
            ? mockMember.holdings
            : mockMember.watchlist;
      expect(new Set(graph.metadata.focusCompanyIds)).toEqual(
        new Set(expected),
      );
      expect(new Set(graph.nodes.map((n) => n.id)).size).toBe(
        graph.nodes.length,
      );
      const naver = graph.nodes.find((n) => n.id === 'KRX:035420');
      expect(naver).toMatchObject({ holding: true, watch: true });
    });
  }
  it('related companies are included, not only the member seed companies', () => {
    const graph = createMockGraph({
      mode: 'personal',
      personalFilter: 'watchlist',
    });
    expect(graph.nodes.find((n) => n.id === 'KRX:030200')).toBeDefined();
    expect(graph.nodes.find((n) => n.id === 'NASDAQ:AAPL')).toBeUndefined();
  });
  it('all edges reference real nodes and shared edges reference common issues', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const ids = new Set(graph.nodes.map((n) => n.id));
    for (const edge of graph.edges) {
      expect(ids.has(edge.source) && ids.has(edge.target)).toBe(true);
      if (edge.derived) {
        expect(edge.evidenceIds).toEqual([]);
        for (const issueId of edge.via) {
          expect(
            graph.edges.some(
              (e) => e.source === issueId && e.target === edge.source,
            ),
          ).toBe(true);
          expect(
            graph.edges.some(
              (e) => e.source === issueId && e.target === edge.target,
            ),
          ).toBe(true);
        }
      }
    }
    expect(
      graph.nodes
        .filter((n) => n.kind === 'issue')
        .every((n) => ['domestic', 'international'].includes(n.geography!)),
    ).toBe(true);
  });
  it('distinguishes no base companies from no relations and keeps the bases', () => {
    const request = { mode: 'personal', personalFilter: 'watchlist' } as const;
    expect(createMockGraph(request, 'empty').nodes).toEqual([]);
    const graph = createMockGraph(request, 'no-relations');
    expect(graph.nodes.map((n) => n.id)).toEqual(mockMember.watchlist);
    expect(graph.edges).toEqual([]);
    expect(graph.metadata.emptyReason).toBe('NO_RELATIONS');
  });
  it('derives counts instead of showing Figma example numbers', () => {
    const graph = createMockGraph({
      mode: 'personal',
      personalFilter: 'watchlist',
    });
    expect(graphSummary(graph)).toMatchObject({
      company: 2,
      holding: 1,
      watch: 1,
      disconnected: 0,
    });
  });
  it('deduplicates companies connected to an issue by multiple direct relation types', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const individualIssue = graph.nodes.find(
      (node) =>
        node.kind === 'issue' && node.label === 'NVIDIA 개별 공시 (예시)',
    )!;
    const original = graph.edges.find(
      (edge) =>
        edge.source === individualIssue.id && edge.target === 'NASDAQ:NVDA',
    )!;
    const before = graphSummary(graph);
    graph.edges.push({
      ...original,
      id: `${original.id}-structural`,
      relationType: 'STRUCTURALLY_RELATED_TO',
    });

    const summary = graphSummary(graph);
    expect(summary.incident.get(individualIssue.id)).toEqual(['NASDAQ:NVDA']);
    expect(summary.sharedIssues).toBe(before.sharedIssues);
    expect(summary.folded.get('NASDAQ:NVDA')).toBe(
      before.folded.get('NASDAQ:NVDA'),
    );
  });
  it('uses five activity sizes based on each company unique issue count', () => {
    expect([0, 1, 2, 4, 100].map((count) => companyNodeSize(count))).toEqual([
      18, 22, 26, 34, 44,
    ]);

    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const rendered = toG6Data(graph, 1245, 705);
    const nvidia = rendered.nodes?.find((node) => node.id === 'NASDAQ:NVDA');
    const samsung = rendered.nodes?.find((node) => node.id === 'KRX:005930');
    expect(nvidia?.style?.size).toBe(26);
    expect(samsung?.style?.size).toBe(44);
  });
  it('G6 data keeps IDs intact and folds single-company events without dangling edges', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const rendered = toG6Data(graph, 1245, 705);
    const ids = new Set(rendered.nodes?.map((n) => n.id));
    expect(rendered.nodes!.length).toBeLessThan(graph.nodes.length);
    expect(
      rendered.edges?.every((e) => ids.has(e.source) && ids.has(e.target)),
    ).toBe(true);
    expect(
      rendered.nodes?.find((n) => n.id === 'NASDAQ:NVDA')?.style?.x,
    ).toBeCloseTo(622.5, 0);
  });
  it('maps UI scope to personalFilter only for personal API requests', () => {
    expect(graphUrl({ mode: 'all', personalFilter: 'watchlist' })).toBe(
      '/api/v1/graph?mode=all',
    );
    expect(graphUrl({ mode: 'personal', personalFilter: 'watchlist' })).toBe(
      '/api/v1/graph?mode=personal&personalFilter=watchlist',
    );
  });
});
