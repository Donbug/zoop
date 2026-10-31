import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import BriefingPage from '@/pages/briefing/BriefingPage';
import { useAuthStore } from '@/stores/useAuthStore';
import type { BriefingItem, BriefingResponse } from '@/types/briefing';
import {
  apiError,
  createFakeServer,
  json,
  deferred,
  type FakeServer,
} from '../support/fakeServer';

// 합성 fixture. 와이어프레임 D-BRF-01(2026-09-17 출근)의 예시를 따른다.
const ROUND = 'brf-2026-09-17-morning';

function item(overrides: Partial<BriefingItem> = {}): BriefingItem {
  return {
    title: 'NVIDIA Vera Rubin NVL72 MLPerf 결과',
    eventId: 'ev-1',
    eventTime: null,
    timePrecision: 'unknown',
    companies: [
      { id: 'nvidia', name: 'NVIDIA' },
      { id: 'samsung', name: '삼성전자' },
    ] as BriefingItem['companies'],
    evidenceIds: ['e'],
    summary: { status: 'unavailable', reason: '검증된 요약 없음' },
    rank: 1,
    reason: '합성 선정 이유',
    evidenceCount: 1,
    matchedCompanyIds: [],
    ...overrides,
  };
}

function briefing(items: BriefingItem[] = [item()]): BriefingResponse {
  return {
    id: ROUND,
    date: '2026-09-17',
    edition: 'morning',
    status: 'published',
    scheduledAt: '2026-09-17T07:40:00+09:00',
    publishedAt: '2026-09-17T07:41:00+09:00',
    generatedAt: '2026-09-17T07:41:00+09:00',
    dataAsOf: '2026-09-17T07:40:00+09:00',
    graphVersion: 'v7',
    marketSummary: { status: 'unavailable', reason: '합성 요약 없음' },
    marketVariables: { status: 'unavailable', reason: '합성 지표 없음' },
    items,
    sinceMorning: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'fixture',
      asOf: '2026-09-17T07:40:00+09:00',
      graphVersion: 'v7',
      requestId: 'r',
      partial: false,
      failures: [],
    },
  };
}

function signInMember(id = 'mem-1') {
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: { id, email: 'member@zoop.test', displayName: '회원' },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: 'csrf-member',
    expiresAt: null,
  });
}

function setup(
  url = '/briefing?reading=full',
  latest: BriefingResponse = briefing(),
) {
  // Legacy full-view feedback/personalization checks retain their original surface.
  if (!new URL(url, 'http://localhost').searchParams.has('reading'))
    url += (url.includes('?') ? '&' : '?') + 'reading=full';
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings', () => json(latest));
  server.on('GET', '/api/v1/briefings/rounds', () =>
    json({ items: [], nextCursor: null }),
  );
  server.on('GET', '/api/v1/feedback', () =>
    json({ items: [], nextCursor: null }),
  );
  render(
    <MemoryRouter initialEntries={[url]}>
      <BriefingPage />
    </MemoryRouter>,
  );
  return { server, user: userEvent.setup() };
}

let server: FakeServer;

beforeEach(() => {
  useAuthStore.getState().clearSession();
});

describe('FS032 핵심 이슈의 회차 기준 지도', () => {
  it('이슈마다 이 회차 관계 그래프에서 그 이슈를 고른 주소로 간다', async () => {
    setup();
    const link = await screen.findByRole('link', {
      name: '이 회차 관계 그래프에서 보기',
    });
    expect(link.getAttribute('href')).toBe(
      `/?round=${ROUND}&select=node%3Aev-1`,
    );
  });
});

describe('FS066-01 브리핑 평가', () => {
  it('비회원에게는 평가 대신 로그인을 안내하고 내 평가를 요청하지 않는다', async () => {
    ({ server } = setup());
    expect(
      (await screen.findAllByText('평가는 로그인한 회원만 남길 수 있어요.'))
        .length,
    ).toBe(2);
    expect(server.calls('GET', '/api/v1/feedback')).toHaveLength(0);
  });

  it('저장된 내 평가를 보여 주고, 싫어요는 이유를 덧붙이며, 다시 누르면 취소한다', async () => {
    signInMember();
    ({ server } = setup());
    server.on('GET', '/api/v1/feedback', (request) =>
      json({
        items:
          request.query.get('feature') === 'briefing_round'
            ? [
                {
                  feature: 'briefing_round',
                  targetId: ROUND,
                  targetVersion: 'v7',
                  value: 'up',
                  reason: null,
                },
              ]
            : [],
        nextCursor: null,
      }),
    );
    server.on('PUT', '/api/v1/feedback', (request) => {
      const body = request.body as Record<string, unknown>;
      return json({
        ...body,
        targetVersion: 'v7',
        reason: body.reason ?? null,
      });
    });
    const { user } = { user: userEvent.setup() };

    const round = await screen.findByRole('group', {
      name: '이 브리핑 회차 평가',
    });
    await waitFor(() =>
      expect(
        within(round)
          .getByRole('button', { name: '이 브리핑 회차: 도움이 됐어요' })
          .getAttribute('aria-pressed'),
      ).toBe('true'),
    );
    const requested = server.calls('GET', '/api/v1/feedback');
    expect(requested.map((call) => call.query.get('targetIds'))).toEqual(
      expect.arrayContaining([ROUND, `${ROUND}/ev-1`]),
    );

    const issue = screen.getByRole('group', { name: '핵심 이슈 1 평가' });
    await user.click(
      within(issue).getByRole('button', {
        name: '핵심 이슈 1: 도움이 안 됐어요',
      }),
    );
    expect(server.calls('PUT', '/api/v1/feedback')[0].body).toEqual({
      feature: 'briefing_issue',
      targetId: `${ROUND}/ev-1`,
      value: 'down',
      targetVersion: 'v7',
      reason: null,
    });
    expect(screen.queryByText('도움이 안 됐다고 남겼어요')).toBeNull();

    await user.type(
      screen.getByPlaceholderText('어떤 점이 아쉬웠나요? (선택)'),
      '근거가 부족해요',
    );
    await user.click(screen.getByRole('button', { name: '이유 보내기' }));
    expect(server.calls('PUT', '/api/v1/feedback')[1].body).toMatchObject({
      value: 'down',
      reason: '근거가 부족해요',
    });

    await user.click(
      within(issue).getByRole('button', {
        name: '핵심 이슈 1: 도움이 안 됐어요',
      }),
    );
    expect(server.calls('PUT', '/api/v1/feedback')[2].body).toMatchObject({
      value: 'none',
    });
    await waitFor(() =>
      expect(
        within(issue)
          .getByRole('button', { name: '핵심 이슈 1: 도움이 안 됐어요' })
          .getAttribute('aria-pressed'),
      ).toBe('false'),
    );
  });

  it('결과 버전이 바뀌어(409) 저장하지 못하면 이전 평가를 두고 새로 고침을 안내한다', async () => {
    signInMember();
    ({ server } = setup());
    server.on('PUT', '/api/v1/feedback', () =>
      apiError(409, 'REVISION_CONFLICT'),
    );
    const user = userEvent.setup();

    const round = await screen.findByRole('group', {
      name: '이 브리핑 회차 평가',
    });
    const up = within(round).getByRole('button', {
      name: '이 브리핑 회차: 도움이 됐어요',
    });
    await waitFor(() => expect((up as HTMLButtonElement).disabled).toBe(false));
    await user.click(up);

    expect(
      await screen.findByText(/결과가 바뀌어 평가를 저장하지 않았어요/),
    ).toBeTruthy();
    expect(up.getAttribute('aria-pressed')).toBe('false');
    // 같은 버전으로 다시 보내도 거절되므로 다시 시도를 두지 않는다.
    expect(
      within(screen.getByRole('alert')).queryByRole('button', {
        name: '다시 시도',
      }),
    ).toBeNull();
    expect(server.calls('PUT', '/api/v1/feedback')).toHaveLength(1);
  });

  it('평가 저장 실패(503)는 같은 목표로 다시 시도한다', async () => {
    signInMember();
    ({ server } = setup());
    let attempts = 0;
    server.on('PUT', '/api/v1/feedback', (request) => {
      attempts += 1;
      return attempts === 1
        ? apiError(503, 'SOURCE_UNAVAILABLE')
        : json({ ...(request.body as object), reason: null });
    });
    const user = userEvent.setup();
    const round = await screen.findByRole('group', {
      name: '이 브리핑 회차 평가',
    });
    const up = within(round).getByRole('button', {
      name: '이 브리핑 회차: 도움이 됐어요',
    });
    await waitFor(() => expect((up as HTMLButtonElement).disabled).toBe(false));
    await user.click(up);

    expect(await screen.findByText(/평가를 저장하지 못했어요/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(up.getAttribute('aria-pressed')).toBe('true'));
    const puts = server.calls('PUT', '/api/v1/feedback');
    expect(puts).toHaveLength(2);
    expect(puts[1].body).toMatchObject({
      feature: 'briefing_round',
      targetId: ROUND,
      value: 'up',
    });
    const putInits = vi
      .mocked(fetch)
      .mock.calls.filter(([, init]) => init?.method === 'PUT')
      .map(([, init]) => new Headers(init?.headers));
    expect(putInits[1].get('X-CSRF-Token')).toBe('csrf-member');
  });

  it('저장을 기다리는 동안 다시 눌러도 한 번만 보낸다', async () => {
    signInMember();
    ({ server } = setup());
    const pending = deferred<Response>();
    server.on('PUT', '/api/v1/feedback', () => pending.promise);
    const user = userEvent.setup();
    const round = await screen.findByRole('group', {
      name: '이 브리핑 회차 평가',
    });
    const up = within(round).getByRole('button', {
      name: '이 브리핑 회차: 도움이 됐어요',
    });
    await waitFor(() => expect((up as HTMLButtonElement).disabled).toBe(false));
    await user.click(up);
    await user.click(up);
    await act(async () =>
      pending.resolve(
        json({
          feature: 'briefing_round',
          targetId: ROUND,
          value: 'up',
          targetVersion: 'v7',
          reason: null,
        }),
      ),
    );
    await waitFor(() => expect(up.getAttribute('aria-pressed')).toBe('true'));
    expect(server.calls('PUT', '/api/v1/feedback')).toHaveLength(1);
  });

  it('결과 버전이 없는 회차는 평가를 읽거나 보내지 않고 이유를 알린다', async () => {
    signInMember();
    ({ server } = setup('/briefing', { ...briefing(), graphVersion: null }));

    expect(
      await screen.findByText(
        '이 회차는 결과 버전이 없어 평가를 남길 수 없어요.',
      ),
    ).toBeTruthy();
    expect(
      screen.queryByRole('group', { name: '이 브리핑 회차 평가' }),
    ).toBeNull();
    expect(server.calls('GET', '/api/v1/feedback')).toHaveLength(0);
  });
});

// FS036 reselection/ownership regressions are covered in personalIssueSelection.test.tsx.

describe('110 final review regressions', () => {
  it('keeps feedback disabled after read failure, then restores the saved vote on retry', async () => {
    signInMember();
    const { server, user } = setup();
    server.on('GET', '/api/v1/feedback', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    await screen.findByText(/내 평가를 불러오지 못해/);
    const up = screen.getByRole('button', {
      name: '이 브리핑 회차: 도움이 됐어요',
    }) as HTMLButtonElement;
    expect(up.disabled).toBe(true);
    expect(server.calls('PUT', '/api/v1/feedback')).toHaveLength(0);
    server.on('GET', '/api/v1/feedback', ({ query }) =>
      json({
        items:
          query.get('feature') === 'briefing_round'
            ? [
                {
                  feature: 'briefing_round',
                  targetId: ROUND,
                  targetVersion: 'v7',
                  value: 'down',
                  reason: null,
                },
              ]
            : [],
        nextCursor: null,
      }),
    );
    await user.click(screen.getByRole('button', { name: '내 평가 다시 확인' }));
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: '이 브리핑 회차: 도움이 안 됐어요' })
          .getAttribute('aria-pressed'),
      ).toBe('true'),
    );
  });
  it('reads later feedback pages before assuming an absent vote', async () => {
    signInMember();
    const { server } = setup();
    server.on('GET', '/api/v1/feedback', ({ query }) =>
      query.get('feature') !== 'briefing_round'
        ? json({ items: [], nextCursor: null })
        : query.has('cursor')
          ? json({
              items: [
                {
                  feature: 'briefing_round',
                  targetId: ROUND,
                  targetVersion: 'v7',
                  value: 'down',
                  reason: null,
                },
              ],
              nextCursor: null,
            })
          : json({ items: [], nextCursor: 'page-2' }),
    );
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: '이 브리핑 회차: 도움이 안 됐어요' })
          .getAttribute('aria-pressed'),
      ).toBe('true'),
    );
    expect(
      server
        .calls('GET', '/api/v1/feedback')
        .some((call) => call.query.get('cursor') === 'page-2'),
    ).toBe(true);
  });
  it('does not acknowledge a vote response for another result', async () => {
    signInMember();
    const { server, user } = setup();
    server.on('PUT', '/api/v1/feedback', ({ body }) =>
      json({ ...(body as object), targetId: 'other-result' }),
    );
    const up = await screen.findByRole('button', {
      name: '이 브리핑 회차: 도움이 됐어요',
    });
    await waitFor(() => expect((up as HTMLButtonElement).disabled).toBe(false));
    await user.click(up);
    await screen.findByText(/평가를 저장하지 못했어요/);
    expect(up.getAttribute('aria-pressed')).toBe('false');
  });
  it('ignores an old member vote response after changing members', async () => {
    signInMember('old-member');
    const { server, user } = setup();
    const pending = deferred<Response>();
    server.on('PUT', '/api/v1/feedback', () => pending.promise);
    const up = await screen.findByRole('button', {
      name: '이 브리핑 회차: 도움이 됐어요',
    });
    await waitFor(() => expect((up as HTMLButtonElement).disabled).toBe(false));
    await user.click(up);
    await act(async () => signInMember('new-member'));
    const fresh = await screen.findByRole('button', {
      name: '이 브리핑 회차: 도움이 됐어요',
    });
    await waitFor(() =>
      expect((fresh as HTMLButtonElement).disabled).toBe(false),
    );
    await act(async () =>
      pending.resolve(
        json({
          feature: 'briefing_round',
          targetId: ROUND,
          targetVersion: 'v7',
          value: 'up',
          reason: null,
        }),
      ),
    );
    expect(fresh.getAttribute('aria-pressed')).toBe('false');
    expect(screen.queryByText('도움이 됐다고 남겼어요')).toBeNull();
  });
});
it.each(['cursor', 'version'])(
  'keeps votes disabled for invalid feedback %s',
  async (field) => {
    signInMember();
    const { server } = setup();
    server.on('GET', '/api/v1/feedback', ({ query }) =>
      query.get('feature') === 'briefing_round'
        ? json(
            field === 'cursor'
              ? { items: [], nextCursor: 'loop' }
              : {
                  items: [
                    {
                      feature: 'briefing_round',
                      targetId: ROUND,
                      targetVersion: 'old',
                      value: 'up',
                      reason: null,
                    },
                  ],
                  nextCursor: null,
                },
          )
        : json({ items: [], nextCursor: null }),
    );
    await screen.findByText(/내 평가를 불러오지 못해/);
    expect(
      (
        screen.getByRole('button', {
          name: '이 브리핑 회차: 도움이 됐어요',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  },
);
it('restores the cookie session on a direct briefing-page visit before loading member votes', async () => {
  signInMember();
  const session = useAuthStore.getState().session;
  useAuthStore.getState().clearSession();
  useAuthStore.setState({ status: 'checking' });
  const server = createFakeServer();
  server.on('GET', '/api/v1/auth/session', () => json(session));
  server.on('GET', '/api/v1/briefings', () => json(briefing()));
  server.on('GET', '/api/v1/briefings/rounds', () =>
    json({ items: [], nextCursor: null }),
  );
  server.on('GET', '/api/v1/feedback', () =>
    json({ items: [], nextCursor: null }),
  );
  render(
    <MemoryRouter initialEntries={['/briefing?reading=full']}>
      <BriefingPage />
    </MemoryRouter>,
  );
  const up = await screen.findByRole('button', {
    name: '이 브리핑 회차: 도움이 됐어요',
  });
  await waitFor(() => expect((up as HTMLButtonElement).disabled).toBe(false));
  expect(server.calls('GET', '/api/v1/auth/session')).toHaveLength(1);
});
