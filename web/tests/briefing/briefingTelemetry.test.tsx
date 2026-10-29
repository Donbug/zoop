import { StrictMode } from 'react';
import { act, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, expect, test } from 'vitest';
import BriefingPage from '@/pages/briefing/BriefingPage';
import { useAuthStore } from '@/stores/useAuthStore';
import { flushTelemetry, resetTelemetry } from '@/util/track';
import type { BriefingResponse } from '@/types/briefing';
import type { Session } from '@/types/auth';
import type { TelemetryEvent } from '@/types/telemetry';
import {
  createFakeServer,
  deferred,
  json,
  apiError,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const endpoint = '/api/v1/telemetry';
const guest: Session = {
  authenticated: false,
  kind: 'guest',
  user: null,
  setup: null,
  csrfToken: 'fixture-csrf',
  expiresAt: null,
};
const time = '2026-10-14T07:40:00+09:00';
// D-BRF-01·02 / FS065: synthetic HTTP responses, no production telemetry.
function round(overrides: Partial<BriefingResponse> = {}): BriefingResponse {
  return {
    id: 'fixture-morning',
    date: '2026-10-14',
    edition: 'morning',
    status: 'published',
    scheduledAt: time,
    publishedAt: time,
    generatedAt: time,
    dataAsOf: time,
    graphVersion: null,
    marketSummary: { status: 'unavailable', reason: '합성 요약 없음' },
    marketVariables: { status: 'unavailable', reason: '합성 지표 없음' },
    items: [
      {
        eventId: 'fixture-event',
        title: '합성 핵심 이슈',
        eventTime: null,
        timePrecision: 'unknown',
        companies: [],
        evidenceIds: [],
        summary: { status: 'unavailable', reason: '합성 상세 없음' },
        rank: 1,
        reason: '합성 선정 이유',
        evidenceCount: 0,
      },
    ],
    sinceMorning: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'fixture',
      asOf: time,
      graphVersion: null,
      requestId: 'fixture-request',
      partial: false,
      failures: [],
    },
    ...overrides,
  };
}
let server: FakeServer;
beforeEach(() => {
  resetTelemetry();
  useAuthStore.getState().setSession(guest);
  server = createFakeServer();
  server.on('POST', endpoint, () => json({ accepted: 1 }, 202));
  server.on('GET', '/api/v1/briefings', () => json(round()));
  server.on('GET', '/api/v1/briefings/rounds', () =>
    json({ items: [], nextCursor: null }),
  );
  server.on('GET', '/api/v1/briefings/:id/items/:eventId', () =>
    apiError(503, 'SOURCE_UNAVAILABLE'),
  );
  server.on('GET', '/api/v1/briefings/:id/items/:eventId/impacts', () =>
    apiError(503, 'SOURCE_UNAVAILABLE'),
  );
});
afterEach(() => resetTelemetry());
function open(strict = false, query = '') {
  return renderRoutes(
    [
      {
        path: '/briefing',
        element: strict ? (
          <StrictMode>
            <BriefingPage />
          </StrictMode>
        ) : (
          <BriefingPage />
        ),
      },
    ],
    `/briefing${query}`,
  );
}
async function events() {
  await act(async () => {
    flushTelemetry();
  });
  return server
    .calls('POST', endpoint)
    .flatMap((call) => (call.body as { events: TelemetryEvent[] }).events);
}

test('D-BRF-01·02 records screen and published round once, then compact issue openings with the round viewId', async () => {
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/briefings', () => pending.promise);
  const { user } = open(true);
  expect((await events()).map((e) => e.type)).toEqual(['screen_view']);
  await act(async () => {
    pending.resolve(json(round()));
  });
  const summary = await screen.findByText('합성 핵심 이슈');
  await user.click(summary);
  await waitFor(async () =>
    expect(
      (await events()).filter((e) => e.type === 'briefing_issue_open'),
    ).toHaveLength(1),
  );
  let sent = await events();
  expect(sent.filter((e) => e.type === 'screen_view')).toHaveLength(1);
  const views = sent.filter((e) => e.type === 'briefing_view');
  expect(views).toHaveLength(1);
  expect(sent.find((e) => e.type === 'briefing_issue_open')).toEqual({
    type: 'briefing_issue_open',
    targetId: 'fixture-event',
    roundId: 'fixture-morning',
    viewId: views[0].viewId,
  });
  await user.click(summary);
  await user.click(summary);
  await waitFor(async () =>
    expect(
      (await events()).filter((e) => e.type === 'briefing_issue_open'),
    ).toHaveLength(2),
  );
  sent = await events();
  expect(sent.filter((e) => e.type === 'briefing_view')).toHaveLength(1);
});

test('D-BRF-01·02 records full-reading detail opening but not closing or a second visible evidence section', async () => {
  const { user } = open(false, '?reading=full');
  await user.click(
    await screen.findByRole('button', { name: '핵심 이슈 1 자세히 보기' }),
  );
  await user.click(
    screen.getByRole('button', { name: '핵심 이슈 1 근거 보기' }),
  );
  await user.click(
    screen.getByRole('button', { name: '핵심 이슈 1 자세히 접기' }),
  );
  expect(
    (await events()).filter((e) => e.type === 'briefing_issue_open'),
  ).toHaveLength(1);
});

test('D-BRF-01·02 records a full-reading issue map link without changing its destination', async () => {
  const { user, router } = open(false, '?reading=full');
  const link = await screen.findByRole('link', {
    name: '이 회차 관계 그래프에서 보기',
  });
  expect(link.getAttribute('href')).toBe(
    '/?round=fixture-morning&select=node%3Afixture-event',
  );
  await user.click(link);
  expect(router.state.location.pathname).toBe('/');
  const sent = await events();
  expect(sent.filter((e) => e.type === 'briefing_issue_open')).toHaveLength(1);
});

test.each(['compact', 'full'])(
  'D-BRF-01·02 records #394 issue-first openings in %s reading without exposing a mismatched map link',
  async (reading) => {
    const result = round();
    result.items[0].evidenceIds = ['fixture-evidence'];
    result.issueIntelligence = {
      schemaVersion: 'issue-intelligence-v1',
      policyVersion: 'issue-selection-policy-v2',
      verificationMode: 'separate_model_request',
      model: 'gpt-6-luna',
      roundId: result.id,
      date: result.date,
      edition: result.edition,
      cutoff: time,
      resultVersion: 'fixture-revision',
      generatedAt: time,
      issues: [
        {
          issueId: 'fixture-event',
          status: 'PASS',
          resultVersion: 'fixture-issue-version',
          headline: {
            text: '합성 검증 문안',
            evidenceIds: ['fixture-evidence'],
          },
          companies: [],
          sources: {
            'fixture-evidence': {
              evidenceId: 'fixture-evidence',
              documentId: 'fixture-document',
              bodySha256: 'a'.repeat(64),
              title: '합성 근거',
              url: 'https://example.test/source',
              publishedAt: time,
              quote: '합성 원문 인용',
            },
          },
        },
      ],
    };
    server.on('GET', '/api/v1/briefings', () => json(result));
    const { user } = open(false, `?reading=${reading}`);
    await user.click(await screen.findByText('합성 핵심 이슈'));
    await waitFor(async () =>
      expect(
        (await events()).filter((e) => e.type === 'briefing_issue_open'),
      ).toHaveLength(1),
    );
    expect(
      screen.queryByRole('link', { name: '이 회차 관계 그래프에서 보기' }),
    ).toBeNull();
    await user.click(screen.getByText('선정 이유'));
    expect(
      (await events()).filter((e) => e.type === 'briefing_issue_open'),
    ).toHaveLength(1);
  },
);

test.each(['not_ready', 'generating', 'failed', 'suspended'] as const)(
  'D-BRF-01·02 does not record an unpublished %s round',
  async (status) => {
    server.on('GET', '/api/v1/briefings', () => json(round({ status })));
    open();
    await waitFor(() =>
      expect(screen.queryByText('브리핑을 불러오고 있어요.')).toBeNull(),
    );
    expect((await events()).map((e) => e.type)).toEqual(['screen_view']);
  },
);

test('D-BRF-01·02 ignores an old round response after navigation and records the displayed evening round', async () => {
  const old = deferred<Response>();
  server.on('GET', '/api/v1/briefings', ({ query }) =>
    query.get('edition') === 'morning'
      ? old.promise
      : json(round({ id: 'fixture-evening', edition: 'evening' })),
  );
  const { router } = open();
  await act(async () => {
    await router.navigate('/briefing?edition=evening');
  });
  await screen.findByText('합성 핵심 이슈');
  await act(async () => {
    old.resolve(json(round()));
  });
  const views = (await events()).filter((e) => e.type === 'briefing_view');
  expect(views.map((e) => e.targetId)).toEqual(['fixture-evening']);
});

test('D-BRF-01·02 keeps the displayed briefing usable when telemetry fails', async () => {
  server.on('POST', endpoint, () => apiError(503, 'SOURCE_UNAVAILABLE'));
  const { user } = open();
  await user.click(await screen.findByText('합성 핵심 이슈'));
  await events();
  expect(
    screen.getByRole('heading', { name: '공통으로 확인된 사실' }),
  ).toBeTruthy();
  expect(screen.queryByText(/계측.*실패/)).toBeNull();
});

test('D-BRF-01·02 never records a failed or mismatched round response as a publication', async () => {
  server.on('GET', '/api/v1/briefings', () => apiError(403, 'FORBIDDEN'));
  const { user } = open();
  await screen.findByText('이 회차를 조회할 권한이 없어요.');
  expect((await events()).map((e) => e.type)).toEqual(['screen_view']);
  server.on('GET', '/api/v1/briefings', () =>
    json(round({ edition: 'evening' })),
  );
  await user.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByText('브리핑을 불러오지 못했어요. 다시 시도해 주세요.');
  expect((await events()).filter((e) => e.type === 'briefing_view')).toEqual(
    [],
  );
});

test('D-BRF-01·02 discards an old session response and pending activity after a member change', async () => {
  const old = deferred<Response>();
  let requests = 0;
  server.on('GET', '/api/v1/briefings', () =>
    ++requests === 1 ? old.promise : json(round({ id: 'new-member-round' })),
  );
  open();
  await waitFor(() => expect(requests).toBe(1));
  await act(async () => {
    useAuthStore.getState().setSession({
      ...guest,
      authenticated: true,
      kind: 'member',
      user: {
        id: 'fixture-member',
        email: 'fixture@example.test',
        displayName: '합성 회원',
      },
      setup: { completed: true, tutorialCompleted: true },
    });
  });
  await screen.findByText('합성 핵심 이슈');
  await act(async () => {
    old.resolve(json(round()));
  });
  const sent = await events();
  expect(
    sent.filter((e) => e.type === 'briefing_view').map((e) => e.targetId),
  ).toEqual(['new-member-round']);
  expect(sent.filter((e) => e.type === 'screen_view')).toHaveLength(1);
});

test('D-BRF-01·02 waits for the guest session and then records the screen and publication', async () => {
  useAuthStore.getState().clearSession();
  useAuthStore.getState().setStatus('checking');
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/auth/session', () => pending.promise);
  open();
  await screen.findByText('합성 핵심 이슈');
  expect(await events()).toEqual([]);
  await act(async () => {
    pending.resolve(json(guest));
  });
  await waitFor(async () =>
    expect((await events()).map((e) => e.type).sort()).toEqual([
      'briefing_view',
      'screen_view',
    ]),
  );
});
