import { beforeEach, expect, it } from 'vitest';
import {
  withCatalogCompanies,
  withMemberCompanies,
} from '@/apis/graph/catalog-companies';
import { createMockGraph } from '@/mocks/graph/response';
import { apiError, createFakeServer, json } from '../support/fakeServer';

// D-GRP-01/01b: catalog companies without events appear as unconnected nodes.
const summary = (id: string, name: string) => ({
  id,
  name,
  ticker: null,
  aliases: [],
  sector: null,
  brandColor: '#123456',
  logoUrl: `/graph-assets/${name}.svg`,
  issueCount: 0,
});
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  server = createFakeServer();
});

it('adds catalog companies missing from the market map without inventing relations', async () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  server.on('GET', '/api/v1/companies', ({ query }) =>
    query.get('cursor')
      ? json({
          items: [summary('ORG:ANTHROPIC', 'anthropic')],
          nextCursor: null,
        })
      : json({
          items: [
            summary('KRX:005930', '삼성전자'),
            summary('KRX:018260', 'sds'),
          ],
          nextCursor: 'next',
        }),
  );
  const result = await withCatalogCompanies(graph);
  const added = result.nodes.slice(graph.nodes.length);
  expect(added.map((node) => node.id)).toEqual(['KRX:018260', 'ORG:ANTHROPIC']);
  expect(added[0]).toMatchObject({
    kind: 'company',
    holding: false,
    watch: false,
    logoUrl: '/graph-assets/sds.svg',
  });
  expect(result.edges).toEqual(graph.edges);
});

it('keeps the map unchanged when the catalog cannot be read', async () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  server.on('GET', '/api/v1/companies', () =>
    apiError(503, 'SOURCE_UNAVAILABLE'),
  );
  expect(await withCatalogCompanies(graph)).toBe(graph);
});

it('builds the mock personal map from the real member and marks companies the mock lacks', async () => {
  const member = { holdings: ['NASDAQ:NVDA'], watchlist: ['KRX:018260'] };
  const graph = createMockGraph(
    { mode: 'personal', personalFilter: 'all' },
    'success',
    member,
  );
  expect(graph.nodes.find((node) => node.id === 'NASDAQ:NVDA')).toMatchObject({
    holding: true,
    isFocus: true,
  });
  server.on('GET', '/api/v1/companies', () =>
    json({ items: [summary('KRX:018260', 'sds')], nextCursor: null }),
  );
  const result = await withMemberCompanies(graph, member);
  expect(result.nodes.find((node) => node.id === 'KRX:018260')).toMatchObject({
    watch: true,
    holding: false,
    isFocus: true,
  });
});
