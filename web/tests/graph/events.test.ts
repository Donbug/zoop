import { afterEach, describe, expect, it, vi } from 'vitest';
import { eventUrl, getEvent } from '@/apis/graph/events';
import { createMockEvent, mockEventEvidence } from '@/mocks/events/fixture';
import { companies, issues } from '@/mocks/graph/fixture';
import {
  formatEventTime,
  safeArticleUrl,
} from '@/components/graph/event-format';
import { createFakeServer, json, apiError } from '../support/fakeServer';

afterEach(() => vi.unstubAllEnvs());
describe('D-GRP-02 · getEvent consumer / ERD v6 fixtures', () => {
  it('uses the versioned public endpoint and preserves round/version/asOf', async () => {
    vi.stubEnv('VITE_GRAPH_DATA_SOURCE', 'api');
    const server = createFakeServer();
    server.on('GET', '/api/v1/events/:id', ({ params }) =>
      json(createMockEvent(params.id)),
    );
    const context = {
      round: 'round-1',
      graphVersion: 'mock-graph-v1',
      asOf: '2026-10-06T03:41:00Z',
    };
    await getEvent('mock-issue-1', context);
    expect(Object.fromEntries(server.requests[0].query)).toEqual(context);
    expect(eventUrl('issue:a/b')).toBe('/api/v1/events/issue%3Aa%2Fb');
  });
  it('does not refresh credentials or redirect on a public endpoint failure', async () => {
    vi.stubEnv('VITE_GRAPH_DATA_SOURCE', 'api');
    const server = createFakeServer();
    server.on('GET', '/api/v1/events/:id', () => apiError(401, 'UNAUTHORIZED'));
    await expect(getEvent('mock-issue-1')).rejects.toMatchObject({
      status: 401,
      code: 'UNAUTHORIZED',
    });
    expect(server.requests).toHaveLength(1);
  });
  it('rejects a different event/version instead of mixing it into the selected map', async () => {
    vi.stubEnv('VITE_GRAPH_DATA_SOURCE', 'api');
    const server = createFakeServer();
    server.on('GET', '/api/v1/events/:id', () =>
      json(createMockEvent('mock-issue-2')),
    );
    await expect(getEvent('mock-issue-1')).rejects.toThrow('일치');
    await expect(
      getEvent('mock-issue-2', { graphVersion: 'other' }),
    ).rejects.toThrow('버전');
  });
  it('keeps shared company/evidence/article IDs intact across all map events', () => {
    for (const issue of issues) {
      const event = createMockEvent(issue.id);
      for (const company of event.companies)
        expect(companies.some((c) => c.id === company.id)).toBe(true);
      for (const id of event.evidenceIds) {
        const evidence = mockEventEvidence.find((e) => e.id === id)!;
        expect(evidence.eventIds).toContain(event.id);
        expect(event.articles.some((a) => a.id === evidence.articleId)).toBe(
          true,
        );
        expect(evidence.end).toBe([...evidence.quote].length);
      }
    }
    expect(() => createMockEvent('missing')).toThrow();
    expect(() =>
      createMockEvent('mock-issue-1', 'success', { round: 'unavailable' }),
    ).toThrow('대체하지');
  });
  it.each([
    [null, 'unknown', '발생 시각 미상'],
    ['2026', 'year', '2026년 · 연도 단위'],
    ['2026-10', 'month', '2026년 10월 · 월 단위'],
    ['2026-10-06', 'day', '2026.10.06 · 날짜 단위'],
    ['2026-10-06T00:00:00Z', 'datetime', '2026-10-06 09:00 KST'],
  ] as const)(
    'preserves time precision (%s / %s)',
    (value, precision, expected) => {
      expect(formatEventTime(value, precision)).toBe(expected);
    },
  );
  it('does not render unsafe article links', () => {
    expect(safeArticleUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeArticleUrl('https://example.com/news')).toBe(
      'https://example.com/news',
    );
  });
});
