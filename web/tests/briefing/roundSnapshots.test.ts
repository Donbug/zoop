import { expect, it } from 'vitest';
import { getGraph } from '@/apis/graph/graph';
import { getEvent } from '@/apis/graph/events';
import { getEvidence } from '@/apis/evidence/evidence';
import { getRelation } from '@/apis/graph/relations';
import { getCompany } from '@/apis/graph/companies';
import { getCompanyIssueImpact } from '@/apis/graph/impact';
import { createFakeServer, json } from '../support/fakeServer';
const context = {
  round: 'fixture-round',
  graphVersion: 'fixture-version',
  asOf: '2026-10-16T07:40:00+09:00',
};
const metadata = { graphVersion: context.graphVersion, asOf: context.asOf };
const request = {
  mode: 'all' as const,
  personalFilter: 'all' as const,
  round: context.round,
};
const basis = {
  roundId: context.round,
  status: 'available',
  graphVersion: context.graphVersion,
  dataAsOf: context.asOf,
  keyIssueIds: [],
  companyIds: [],
};

it('distinguishes a missing historical recording without fetching the current graph', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings/:id/graph', () =>
    json({
      ...basis,
      status: 'unavailable',
      graphVersion: null,
      unavailableReason: 'snapshot_not_recorded',
      message: '당시 저장된 그래프가 없습니다.',
    }),
  );
  await expect(getGraph(request)).rejects.toMatchObject({
    name: 'BriefingGraphUnavailableError',
    reason: 'snapshot_not_recorded',
  });
  expect(server.calls('GET', '/api/v1/graph')).toHaveLength(0);
});

it.each([true, false])(
  'validates canonical round targets in the graph (present=%s)',
  async (present) => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings/:id/graph', () =>
      json({
        ...basis,
        keyIssueIds: ['event-original'],
        companyIds: ['company-original'],
      }),
    );
    server.on('GET', '/api/v1/graph', () =>
      json({
        nodes: present
          ? [
              { id: 'event-original', kind: 'issue' },
              { id: 'company-original', kind: 'company' },
            ]
          : [],
        edges: [],
        metadata,
      }),
    );
    if (present) expect((await getGraph(request)).nodes).toHaveLength(2);
    else await expect(getGraph(request)).rejects.toThrow('핵심 이슈·관련 기업');
  },
);

it.each(['suspended', 'unavailable', 'not_published'])(
  'blocks %s round before requesting a graph',
  async (status) => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings/:id/graph', () =>
      json({ ...basis, status }),
    );
    await expect(getGraph(request)).rejects.toThrow();
    expect(server.calls('GET', '/api/v1/graph')).toHaveLength(0);
  },
);
it.each(['version', 'time', 'round'])(
  'rejects a mismatched %s instead of showing a current graph',
  async (field) => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings/:id/graph', () =>
      json({ ...basis, ...(field === 'round' ? { roundId: 'other' } : {}) }),
    );
    server.on('GET', '/api/v1/graph', () =>
      json({
        nodes: [],
        edges: [],
        metadata: {
          ...metadata,
          ...(field === 'version'
            ? { graphVersion: 'latest' }
            : { asOf: '2026-10-16T18:10:00+09:00' }),
        },
      }),
    );
    await expect(getGraph(request)).rejects.toThrow();
  },
);
it('pins graph query to publication basis and accepts equivalent UTC time', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings/:id/graph', () => json(basis));
  server.on('GET', '/api/v1/graph', () =>
    json({
      nodes: [],
      edges: [],
      metadata: { ...metadata, asOf: '2026-10-15T22:40:00Z' },
    }),
  );
  await getGraph(request);
  const query = server.calls('GET', '/api/v1/graph')[0].query;
  expect(query.get('round')).toBe(context.round);
  expect(query.get('graphVersion')).toBe(context.graphVersion);
  expect(query.get('asOf')).toBe(context.asOf);
});
const consumers = [
  [
    '/api/v1/events/:id',
    '/api/v1/events/fixture',
    () => getEvent('fixture', context),
  ],
  [
    '/api/v1/evidence/:id',
    '/api/v1/evidence/fixture',
    () => getEvidence('fixture', context),
  ],
  [
    '/api/v1/graph/edges/:id',
    '/api/v1/graph/edges/fixture',
    () => getRelation('fixture', context),
  ],
  [
    '/api/v1/companies/:id',
    '/api/v1/companies/fixture',
    () => getCompany('fixture', context),
  ],
  [
    '/api/v1/companies/:id/issues/:issue/impact',
    '/api/v1/companies/fixture/issues/event/impact',
    () => getCompanyIssueImpact('fixture', 'event', context),
  ],
] as const;
it.each(consumers)(
  'round detail %s bypasses development mocks and uses the pinned context',
  async (pattern, _path, load) => {
    const server = createFakeServer();
    server.on('GET', pattern, () =>
      json({ id: 'fixture', companyId: 'fixture', issueId: 'event', metadata }),
    );
    await load();
    const query = server.calls('GET', pattern)[0].query;
    expect(query.get('round')).toBe(context.round);
    expect(query.get('graphVersion')).toBe(context.graphVersion);
    expect(query.get('asOf')).toBe(context.asOf);
    server.on('GET', pattern, () =>
      json({
        id: 'fixture',
        companyId: 'fixture',
        issueId: 'event',
        metadata: { ...metadata, graphVersion: 'other' },
      }),
    );
    await expect(load()).rejects.toThrow();
  },
);
