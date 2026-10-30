import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import PersonalizedIssueSelection from '@/components/briefing/PersonalizedIssueSelection';
import { useAuthStore } from '@/stores/useAuthStore';
import type { PersonalBriefingSelection } from '@/types/personalBriefing';
import {
  apiError,
  createFakeServer,
  json,
  deferred,
} from '../support/fakeServer';
const cutoff = '2026-10-22T00:20:00Z';
function member(id = 'one') {
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: {
      id,
      email: 'synthetic@example.invalid',
      displayName: '[합성] 회원',
    },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: 'synthetic',
    expiresAt: null,
  });
}
function result(): PersonalBriefingSelection {
  return {
    roundId: 'r',
    dataAsOf: cutoff,
    policyVersion: 'personal-issue-selection-v1',
    basisObservedAt: cutoff,
    basis: {
      holdings: ['a'],
      watchlist: ['b'],
      holdingsKind: 'connected_mock_portfolio',
    },
    poolVersion: 'pool',
    scope: 'historical_simulation',
    status: 'available',
    message: null,
    eligibleCount: 8,
    matchingCount: 4,
    excludedByCurrentAccess: 0,
    previousRoundId: 'prev',
    trackingStatus: 'available',
    items: [
      {
        issueId: 'not-in-common-three',
        title: '[합성] 공통 3개 밖의 독립 사건',
        importance: 2,
        whyImportant: '새 생산 계약',
        whyNow: '계약 확정',
        analysis: null,
        nextCheck: null,
        matches: [
          {
            companyId: 'b',
            name: '[합성] 관심기업',
            reason: '이번 계약의 직접 당사자',
            directness: 'direct',
            kinds: ['watchlist'],
          },
        ],
        sources: [
          {
            evidenceId: 'e',
            quote: '[합성] 원문 인용',
            url: 'https://example.invalid/source',
            publishedAt: cutoff,
          },
        ],
      },
    ],
    tracking: [
      {
        issueId: 'old-issue',
        title: '[합성] 이전 계약',
        companyId: 'a',
        companyName: '[합성] 보유기업',
        status: 'not_observed',
        message: '후속 자료 없음 · 확인 완료를 뜻하지 않음',
        nextCheck: '납품 일정 확인',
        basis: 'current_companies_replayed_on_fixed_previous_pool',
      },
    ],
  };
}
function mount() {
  const server = createFakeServer();
  // Install handlers synchronously before React starts the first private GET.
  queueMicrotask(() =>
    render(
      <MemoryRouter>
        <PersonalizedIssueSelection roundId="r" dataAsOf={cutoff} />
      </MemoryRouter>,
    ),
  );
  return server;
}
beforeEach(() => useAuthStore.getState().clearSession());
it('shows whole-pool selection, union basis, relation and existing evidence without quote/AI calls', async () => {
  member();
  const server = mount();
  server.on('GET', '/api/v1/briefings/:id/personalized/issues', () =>
    json(result()),
  );
  expect(
    await screen.findByText('[합성] 공통 3개 밖의 독립 사건'),
  ).toBeTruthy();
  expect(screen.getByText(/전체 적격 후보 8개 중 관련 4개/)).toBeTruthy();
  expect(screen.getByText(/보유 1개 · 관심 1개/)).toBeTruthy();
  expect(screen.getByText('이번 계약의 직접 당사자')).toBeTruthy();
  await userEvent.click(screen.getByText('확인된 근거 1건과 상세 보기'));
  expect(
    screen.getByText(/이 후보의 상세 전망은 저장되어 있지 않습니다/),
  ).toBeTruthy();
  expect(
    screen.getByRole('link', { name: '원문 보기' }).getAttribute('href'),
  ).toBe('https://example.invalid/source');
  expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(0);
  await userEvent.click(screen.getByText('이전 이슈 추적 (1)'));
  expect(
    screen.getByText('후속 자료 없음 · 확인 완료를 뜻하지 않음'),
  ).toBeTruthy();
});
it.each([
  'no_companies',
  'pool_unavailable',
  'no_matching_issues',
  'sources_unavailable',
] as const)(
  'distinguishes %s without filling from common three',
  async (status) => {
    member();
    const server = mount();
    server.on('GET', '/api/v1/briefings/:id/personalized/issues', () =>
      json({
        ...result(),
        status,
        message: `[합성] ${status}`,
        items: [],
        tracking: [],
      }),
    );
    expect(await screen.findByText(`[합성] ${status}`)).toBeTruthy();
    expect(screen.queryByText('[합성] 공통 3개 밖의 독립 사건')).toBeNull();
  },
);
it('does not request private data as a guest', async () => {
  const server = mount();
  expect(await screen.findByText(/로그인 후 확인/)).toBeTruthy();
  expect(
    server.calls('GET', '/api/v1/briefings/:id/personalized/issues'),
  ).toHaveLength(0);
});
it('retries a failure while preserving common briefing access', async () => {
  member();
  const server = mount();
  let n = 0;
  server.on('GET', '/api/v1/briefings/:id/personalized/issues', () =>
    ++n === 1 ? apiError(503, 'SOURCE_UNAVAILABLE') : json(result()),
  );
  await screen.findByRole('alert');
  await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  expect(
    await screen.findByText('[합성] 공통 3개 밖의 독립 사건'),
  ).toBeTruthy();
});
it('hides previous member data and ignores late previous-member responses', async () => {
  member();
  const server = mount();
  const pending = deferred<Response>();
  server.on(
    'GET',
    '/api/v1/briefings/:id/personalized/issues',
    () => pending.promise,
  );
  await waitFor(() =>
    expect(
      server.calls('GET', '/api/v1/briefings/:id/personalized/issues'),
    ).toHaveLength(1),
  );
  server.on('GET', '/api/v1/briefings/:id/personalized/issues', () =>
    json({
      ...result(),
      status: 'no_companies',
      message: '[합성] 새 회원',
      items: [],
      tracking: [],
    }),
  );
  await act(async () => member('two'));
  await screen.findByText('[합성] 새 회원');
  await act(async () => pending.resolve(json(result())));
  expect(screen.queryByText('[합성] 공통 3개 밖의 독립 사건')).toBeNull();
});
it.each(['roundId', 'dataAsOf'])('rejects mismatched %s', async (field) => {
  member();
  const server = mount();
  server.on('GET', '/api/v1/briefings/:id/personalized/issues', () =>
    json({ ...result(), [field]: 'different' }),
  );
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.queryByText('[합성] 공통 3개 밖의 독립 사건')).toBeNull();
});
