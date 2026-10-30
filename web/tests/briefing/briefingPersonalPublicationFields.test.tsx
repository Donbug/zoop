import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it } from 'vitest';
import { usePersonalBriefing } from '@/hooks/usePersonalBriefing';
import { useAuthStore } from '@/stores/useAuthStore';
import type { BriefingResponse } from '@/types/briefing';
import { createFakeServer, json } from '../support/fakeServer';

const at = '2026-10-08T00:20:00Z';
function publication(): BriefingResponse {
  return {
    id: 'fixture-round',
    date: '2026-10-08',
    edition: 'morning',
    status: 'published',
    scheduledAt: at,
    publishedAt: at,
    generatedAt: at,
    dataAsOf: at,
    graphVersion: 'fixture-v1',
    items: [
      {
        eventId: 'fixture-event',
        title: '합성 이슈',
        rank: 1,
        eventTime: null,
        timePrecision: 'unknown',
        companies: [
          {
            id: 'fixture-company',
            name: '합성 기업',
            role: null,
            roleUnconfirmed: false,
            relationType: 'INVOLVES',
          },
        ],
        summary: { status: 'unavailable', reason: '합성 요약 없음' },
        reason: '합성 선정 이유',
        evidenceIds: ['fixture-evidence'],
        evidenceCount: 1,
        sourceSupport: { articleCount: 0 },
        documentSentiments: [
          {
            articleId: 'fixture-article',
            sentiment: {
              label: 'negative',
              companyId: 'fixture-company',
              rationale: '합성 판정 근거',
              quotes: ['합성 인용'],
              judgedAt: at,
              model: 'fixture-model',
              promptVersion: 'fixture-prompt',
            },
          },
        ],
      },
    ],
    marketSummary: { status: 'unavailable', reason: '합성 시장 요약 없음' },
    marketVariables: { status: 'unavailable', reason: '합성 지표 없음' },
    sinceMorning: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'fixture',
      asOf: at,
      graphVersion: 'fixture-v1',
      requestId: 'fixture-request',
      partial: false,
      failures: [],
    },
  };
}

beforeEach(() => {
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: {
      id: 'fixture-member',
      email: 'fixture@zoop.test',
      displayName: '합성 회원',
    },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: 'fixture-csrf',
    expiresAt: null,
  });
});

function load(round: BriefingResponse, personalized: BriefingResponse) {
  const server = createFakeServer();
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      connection: null,
      mockAsOf: null,
      valuation: null,
      holdings: [{ companyId: 'fixture-company', name: '합성 기업' }],
    }),
  );
  personalized.items[0].matchedCompanyIds = ['fixture-company'];
  server.on('GET', '/api/v1/briefings/:id/personalized', () =>
    json(personalized),
  );
  return renderHook(() => usePersonalBriefing(round));
}

// D-BRF-01·02 / FS036: personalization may annotate matches, never replace publication fields.
it.each([
  'article-count',
  'sentiment',
  'missing-support',
  'missing-sentiments',
])('D-BRF-01 rejects personalized publication mismatch: %s', async (change) => {
  const round = publication(),
    personalized = structuredClone(round);
  const item = personalized.items[0];
  if (change === 'article-count') item.sourceSupport = { articleCount: 999 };
  if (change === 'sentiment')
    item.documentSentiments![0].sentiment.label = 'positive';
  if (change === 'missing-support') delete item.sourceSupport;
  if (change === 'missing-sentiments') delete item.documentSentiments;
  const { result } = load(round, personalized);
  await waitFor(() => expect(result.current.state.status).toBe('error'));
  expect('briefing' in result.current.state).toBe(false);
});

it.each([true, false])(
  'D-BRF-01 accepts unchanged publication fields (present=%s)',
  async (present) => {
    const round = publication();
    if (!present) {
      delete round.items[0].sourceSupport;
      delete round.items[0].documentSentiments;
    }
    const personalized = structuredClone(round);
    const { result } = load(round, personalized);
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    if (result.current.state.status !== 'ready') throw new Error('not ready');
    expect(result.current.state.briefing?.items[0].sourceSupport).toEqual(
      round.items[0].sourceSupport,
    );
    expect(result.current.state.briefing?.items[0].documentSentiments).toEqual(
      round.items[0].documentSentiments,
    );
    expect(result.current.state.briefing?.items[0].matchedCompanyIds).toEqual([
      'fixture-company',
    ]);
  },
);
