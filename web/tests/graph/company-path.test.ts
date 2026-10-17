import { describe, expect, it } from 'vitest';
import { companyPath } from '@/components/graph/company-path';
import { createMockGraph } from '@/mocks/graph/response';

describe('D-GRP-07 · two-company path', () => {
  it('keeps the underlying issue instead of taking a derived company shortcut', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const path = companyPath(graph, 'KRX:005930', 'NASDAQ:NVDA');
    expect(path?.nodes.map((n) => n.kind)).toEqual([
      'company',
      'issue',
      'company',
    ]);
    expect(path?.edgeIds).toHaveLength(2);
    expect(
      companyPath(graph, 'NASDAQ:NVDA', 'KRX:005930')?.edgeIds,
    ).toHaveLength(2);
  });
  it('does not fabricate a path from derived, dangling or missing nodes', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    expect(
      companyPath(
        {
          ...graph,
          edges: graph.edges.filter((e) => e.relationType === 'SHARES_ISSUE'),
        },
        'KRX:005930',
        'NASDAQ:NVDA',
      ),
    ).toBeNull();
    expect(companyPath(graph, 'missing', 'NASDAQ:NVDA')).toBeNull();
    expect(companyPath(graph, 'KRX:005930', 'KRX:005930')).toBeNull();
    expect(companyPath(graph, 'mock-issue-1', 'NASDAQ:NVDA')).toBeNull();
  });
});
