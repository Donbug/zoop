import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it } from 'vitest';
import BriefingRecap from '@/components/briefing/BriefingRecap';
import PublishedBriefing from '@/components/briefing/PublishedBriefing';
import { getBriefingRecap } from '@/apis/briefing/briefing';
import { useAuthStore } from '@/stores/useAuthStore';
import type {
  BriefingResponse,
  BriefingRecap as Recap,
} from '@/types/briefing';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';

// D-BRF-01·02 합성 대조 자료. 새 이슈·실제 시장 관측을 만들지 않는다.
const unavailable = { status: 'unavailable', reason: '합성 미저장' } as const;
function prior(): BriefingResponse {
  return {
    id: 'prior-round',
    date: '2026-10-08',
    edition: 'morning',
    status: 'published',
    scheduledAt: '2026-10-08T00:20:00Z',
    publishedAt: '2026-10-08T00:21:00Z',
    generatedAt: '2026-10-08T00:21:00Z',
    dataAsOf: '2026-10-08T00:20:00Z',
    graphVersion: null,
    items: [
      {
        eventId: 'old-event',
        title: '[합성시험] 이전 공급 계획',
        rank: 1,
        reason: '이전 선정 이유',
        eventTime: null,
        timePrecision: 'unknown',
        companies: [],
        evidenceCount: 1,
        evidenceIds: ['old-evidence'],
        summary: {
          text: '[합성시험] 당시 보존된 요약',
          evidenceIds: ['old-evidence'],
          generatedAt: '2026-10-08T00:21:00Z',
          resultVersion: 'old-summary',
        },
      },
    ],
    marketSummary: unavailable,
    marketVariables: unavailable,
    sinceMorning: null,
    previousComparison: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'synthetic-test',
      asOf: '2026-10-08T00:20:00Z',
      graphVersion: null,
      requestId: 'test',
      partial: false,
      failures: [],
    },
  };
}
function quiet(): BriefingResponse {
  return {
    ...prior(),
    id: 'quiet-evening',
    edition: 'evening',
    dataAsOf: '2026-10-08T08:30:00Z',
    emptyReason: 'no_issues_in_window',
    items: [],
    sinceMorning: {
      status: 'available',
      morningRoundId: 'prior-round',
      morningDataAsOf: prior().dataAsOf!,
      morningPublishedAt: prior().publishedAt,
      items: [],
    },
  };
}
function recap(round = quiet()): Recap {
  return {
    roundId: round.id,
    graphVersion: round.graphVersion,
    dataAsOf: round.dataAsOf,
    status: 'available',
    message: '과거 원문 복기',
    reason: null,
    previous: prior(),
  };
}
const path = '/api/v1/briefings/:id/recap';
beforeEach(() => useAuthStore.getState().clearSession());

it('과거 표시와 전문 링크를 유지하고 간단히에서는 펼쳐야 이전 요약을 읽는다', async () => {
  const server = createFakeServer();
  server.on('GET', path, () => json(recap()));
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <BriefingRecap round={quiet()} compact />
    </MemoryRouter>,
  );
  expect(await screen.findByText(/이전 발행:/)).toBeTruthy();
  expect(
    screen.getByText(/이번 회차에 다시 평가한 전망이 아닙니다/),
  ).toBeTruthy();
  expect(
    screen.getByText('[합성시험] 당시 보존된 요약').closest('details')?.open,
  ).toBe(false);
  await user.click(screen.getByText(/이전 이슈 ·/));
  expect(screen.getByText('[합성시험] 당시 보존된 요약')).toBeTruthy();
  expect(
    screen.getByRole('link', { name: /이전 브리핑 전문/ }).getAttribute('href'),
  ).toBe('/briefing?date=2026-10-08&edition=morning&reading=full');
  expect(server.requests).toHaveLength(1);
  server.on('GET', '/api/v1/briefings/:roundId/items/:eventId', () =>
    apiError(404, 'RESOURCE_NOT_FOUND'),
  );
  await user.click(
    screen.getByRole('button', { name: '핵심 이슈 1 근거 보기' }),
  );
  await waitFor(() =>
    expect(
      server.calls('GET', '/api/v1/briefings/:roundId/items/:eventId'),
    ).toHaveLength(1),
  );
  expect(
    server.calls('GET', '/api/v1/briefings/:roundId/items/:eventId')[0].params,
  ).toEqual({ roundId: prior().id, eventId: 'old-event' });
});

it('응답의 다른 이전 회차·현재 버전·시점은 표시하지 않는다', async () => {
  const server = createFakeServer();
  for (const change of [
    { roundId: 'other' },
    { graphVersion: 'new' },
    { dataAsOf: prior().dataAsOf },
    { previous: { ...prior(), id: 'latest' } },
  ]) {
    server.on('GET', path, () => json({ ...recap(), ...change }));
    await expect(getBriefingRecap(quiet())).rejects.toThrow();
  }
});

it('권한 확인 실패는 다시 확인 가능하며 과거 문안을 노출하지 않는다', async () => {
  const server = createFakeServer();
  server.on('GET', path, () => apiError(503, 'SOURCE_UNAVAILABLE'));
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <BriefingRecap round={quiet()} compact={false} />
    </MemoryRouter>,
  );
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.queryByText('[합성시험] 이전 공급 계획')).toBeNull();
  server.on('GET', path, () => json(recap()));
  await user.click(screen.getByRole('button', { name: '복기 다시 확인' }));
  expect(await screen.findByText('[합성시험] 당시 보존된 요약')).toBeTruthy();
});

it('회차 전환 뒤 늦게 도착한 이전 요청으로 복기 영역을 덮지 않는다', async () => {
  const server = createFakeServer();
  const pending = deferred<Response>();
  server.on('GET', path, ({ params }) =>
    params.id === quiet().id
      ? pending.promise
      : json({
          ...recap(),
          roundId: 'other-round',
          status: 'unavailable',
          previous: null,
          message: '고정 이전 회차 없음',
        }),
  );
  const view = render(
    <MemoryRouter>
      <BriefingRecap round={quiet()} compact={false} />
    </MemoryRouter>,
  );
  await waitFor(() => expect(server.requests).toHaveLength(1));
  view.rerender(
    <MemoryRouter>
      <BriefingRecap
        round={{ ...quiet(), id: 'other-round' }}
        compact={false}
      />
    </MemoryRouter>,
  );
  expect(await screen.findByText('고정 이전 회차 없음')).toBeTruthy();
  await act(async () => pending.resolve(json(recap())));
  expect(screen.queryByText('[합성시험] 당시 보존된 요약')).toBeNull();
});

it.each([
  'failed',
  'not_ready',
  'generating',
  'suspended',
  'published',
] as const)(
  '빈 항목만 있는 %s 상태를 정상 무소식 회차로 간주하지 않는다',
  async (status) => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings', () =>
      json({ ...quiet(), status, emptyReason: null }),
    );
    render(
      <MemoryRouter>
        <PublishedBriefing date="2026-10-08" edition="evening" />
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole('heading', { name: '퇴근 브리핑' }),
    ).toBeTruthy();
    expect(
      screen.queryByRole('heading', { name: /이전 브리핑 복기/ }),
    ).toBeNull();
    expect(server.calls('GET', path)).toHaveLength(0);
  },
);
