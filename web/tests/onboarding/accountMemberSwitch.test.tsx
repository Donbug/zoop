import { act, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test } from 'vitest';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import VirtualAccountPage from '@/pages/onboarding/account/VirtualAccountPage';
import { loadSession } from '@/apis/auth/member-session';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Session } from '@/types/auth';
import { createFakeServer, deferred, json } from '../support/fakeServer';
import {
  connectedPortfolioBody,
  mockPortfoliosBody,
} from '../support/fixtures';
import { renderRoutes } from '../support/renderRoutes';

// D-ONB-02 / FS054: 공통 보호 라우트 아래 계좌 단계에서도 회원이 바뀌면 이전 회원의 계좌를 버린다.
function member(id: string): Session {
  return {
    authenticated: true,
    kind: 'member',
    user: { id, email: `${id}@example.test`, displayName: id },
    setup: { completed: false, tutorialCompleted: false },
    csrfToken: `csrf-${id}`,
    expiresAt: null,
  };
}
beforeEach(() => {
  useAuthStore.getState().setSession(member('member-a'));
});

test('지연된 세션 재확인이 다른 회원을 돌려주면 이전 회원의 계좌 정보를 지우고 새 회원으로 다시 조회한다', async () => {
  const server = createFakeServer();
  let owner = 'A';
  server.on('GET', '/api/v1/portfolio/mock-portfolios', () =>
    json(mockPortfoliosBody()),
  );
  server.on('GET', '/api/v1/portfolio', () =>
    json(connectedPortfolioBody(undefined, `회원${owner} 계좌`)),
  );
  renderRoutes(
    [
      {
        element: <ProtectedRoute />,
        children: [
          { path: '/onboarding/account', element: <VirtualAccountPage /> },
        ],
      },
    ],
    '/onboarding/account',
  );
  expect(await screen.findByText(/회원A 계좌/)).toBeTruthy();
  const portfolioReads = server.calls('GET', '/api/v1/portfolio').length;

  const pending = deferred<Response>();
  server.on('GET', '/api/v1/auth/session', () => pending.promise);
  let check!: Promise<unknown>;
  await act(async () => {
    check = loadSession(true).catch(() => null);
  });
  // 재확인 중에는 화면을 내리지 않는다.
  expect(screen.getByText(/회원A 계좌/)).toBeTruthy();

  owner = 'B';
  await act(async () => {
    pending.resolve(json(member('member-b')));
    await check;
  });
  expect(await screen.findByText(/회원B 계좌/)).toBeTruthy();
  expect(screen.queryByText(/회원A 계좌/)).toBeNull();
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/portfolio').length).toBeGreaterThan(
      portfolioReads,
    ),
  );
});
