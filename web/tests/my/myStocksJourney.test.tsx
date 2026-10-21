import { act, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import MyStocksPage from '@/pages/my/MyStocksPage';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import { useAuthStore } from '@/stores/useAuthStore';
import { loadSession } from '@/apis/auth/member-session';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';
import { myMember } from '../support/myMember';
import {
  connectedPortfolioBody,
  connectionBody,
  settingsBody,
} from '../support/fixtures';
import { renderRoutes } from '../support/renderRoutes';

// #51 / WBS 6.4.8 / FS027·FS054·FS062 / D-MY-01·01b.
// Real protected page, API transport and stores; HTTP responses are synthetic.
function member(id = 'member-a'): Session {
  return {
    authenticated: true,
    kind: 'member',
    user: { id, email: `${id}@example.test`, displayName: id },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: `csrf-${id}`,
    expiresAt: null,
  };
}
beforeEach(() => {
  useAuthStore.getState().setSession(member());
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
});
function open() {
  return renderRoutes(
    [
      {
        element: <ProtectedRoute />,
        children: [{ path: '/my', element: <MyStocksPage /> }],
      },
      { path: '/login', element: <p>로그인 목적지</p> },
      { path: '/away', element: <p>다른 화면</p> },
    ],
    '/my',
  );
}
async function search(user: ReturnType<typeof open>['user'], text = '삼성') {
  const box = within(
    await screen.findByRole('search', { name: '관심 종목 추가' }),
  ).getByRole('searchbox');
  await user.type(box, `${text}{Enter}`);
  return screen.findByRole('list', { name: `‘${text}’ 검색 결과` });
}
const watch = () => screen.findByRole('region', { name: '관심 종목' });

test('회원 교체 시 이전 조회·검색을 폐기하고 늦은 이전 응답을 새 목록에 반영하지 않는다', async () => {
  const server = createFakeServer();
  myMember(server, { connected: true, watchlistIds: ['cmp-nvidia'] });
  const settings = deferred<Response>();
  const portfolio = deferred<Response>();
  server.on('GET', '/api/v1/me/settings', () => settings.promise);
  server.on('GET', '/api/v1/portfolio', () => portfolio.promise);
  open();
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(1),
  );
  myMember(server, { watchlistIds: ['cmp-samsung'] });
  await act(async () => useAuthStore.getState().setSession(member('member-b')));
  await screen.findByRole('button', { name: '삼성전자 관심 종목에서 빼기' });
  expect(screen.getByText('연결 안 됨')).toBeTruthy();
  await act(async () => {
    settings.resolve(
      json(settingsBody({ watchlistIds: ['cmp-nvidia'], completed: true })),
    );
    portfolio.resolve(json(connectedPortfolioBody()));
  });
  expect(
    screen.queryByRole('button', { name: 'NVIDIA 관심 종목에서 빼기' }),
  ).toBeNull();
  expect(screen.queryByRole('list', { name: '보유 종목 목록' })).toBeNull();
});

test.each(['success', 'failure', 'expired'] as const)(
  '회원 교체 후 이전 관심 저장 %s가 새 목록·검색·오류를 바꾸지 않는다',
  async (outcome) => {
    const server = createFakeServer();
    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    const pending = deferred<Response>();
    server.on('PUT', '/api/v1/me/watchlist/:id', () => pending.promise);
    const { user } = open();
    await search(user);
    await user.click(
      await screen.findByRole('button', { name: 'NVIDIA 관심 종목에서 빼기' }),
    );
    myMember(server, { watchlistIds: ['cmp-samsung'] });
    await act(async () =>
      useAuthStore.getState().setSession(member('member-b')),
    );
    await screen.findByRole('button', { name: '삼성전자 관심 종목에서 빼기' });
    await act(async () =>
      pending.resolve(
        outcome === 'success'
          ? json(settingsBody({ completed: true, watchlistIds: [] }))
          : outcome === 'expired'
            ? apiError(401, 'AUTH_REQUIRED')
            : apiError(503, 'SOURCE_UNAVAILABLE'),
      ),
    );
    expect(
      screen.getByRole('button', { name: '삼성전자 관심 종목에서 빼기' }),
    ).toBeTruthy();
    expect(screen.queryByRole('list', { name: '‘삼성’ 검색 결과' })).toBeNull();
    expect((screen.getByRole('searchbox') as HTMLInputElement).value).toBe('');
    expect(screen.queryByText(/목록을 이전 상태로 되돌렸어요/)).toBeNull();
    expect(useAuthStore.getState().member?.id).toBe('member-b');
  },
);

test('같은 회원의 세션 갱신은 관심 검색어와 목록을 유지한다', async () => {
  const server = createFakeServer();
  myMember(server, { watchlistIds: ['cmp-nvidia'] });
  const { user } = open();
  await search(user);
  await act(async () =>
    useAuthStore
      .getState()
      .setSession({ ...member(), csrfToken: 'refreshed-csrf' }),
  );
  expect(screen.getByRole('list', { name: '‘삼성’ 검색 결과' })).toBeTruthy();
  expect((screen.getByRole('searchbox') as HTMLInputElement).value).toBe(
    '삼성',
  );
  expect(
    screen.getByRole('button', { name: 'NVIDIA 관심 종목에서 빼기' }),
  ).toBeTruthy();
});

test('이전 계좌 연결의 늦은 성공이 새 회원을 연결 화면으로 되돌리지 않는다', async () => {
  const server = createFakeServer();
  myMember(server);
  const pending = deferred<Response>();
  server.on('POST', '/api/v1/portfolio/connections', () => pending.promise);
  const { user, router, location } = open();
  await user.click(
    await screen.findByRole('button', { name: '가상 계좌 연결하기' }),
  );
  await user.click(
    await screen.findByRole('button', { name: '선택한 가상 계좌 연결하기' }),
  );
  await waitFor(() =>
    expect(server.calls('POST', '/api/v1/portfolio/connections')).toHaveLength(
      1,
    ),
  );
  myMember(server, { watchlistIds: ['cmp-samsung'] });
  await act(async () => {
    useAuthStore.getState().setSession(member('member-b'));
    await router.navigate('/my');
  });
  await screen.findByRole('button', { name: '삼성전자 관심 종목에서 빼기' });
  await act(async () => pending.resolve(json(connectionBody(), 201)));
  expect(location()).toBe('/my');
  expect(
    screen.queryByRole('heading', { name: '가상 계좌를 연결했어요' }),
  ).toBeNull();
});

test('이전 계좌 해제 실패는 새 회원으로 복구 조회를 보내지 않는다', async () => {
  const server = createFakeServer();
  myMember(server, { connected: true, watchlistIds: ['cmp-nvidia'] });
  const pending = deferred<Response>();
  server.on(
    'DELETE',
    '/api/v1/portfolio/connections/:id',
    () => pending.promise,
  );
  const { user } = open();
  await user.click(await screen.findByRole('button', { name: '연결 끊기' }));
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: '연결 끊기',
    }),
  );
  myMember(server, { watchlistIds: ['cmp-samsung'] });
  await act(async () => useAuthStore.getState().setSession(member('member-b')));
  await screen.findByRole('button', { name: '삼성전자 관심 종목에서 빼기' });
  const reads = server.calls('GET', '/api/v1/portfolio').length;
  await act(async () => pending.resolve(apiError(503, 'SOURCE_UNAVAILABLE')));
  expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(reads);
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('관심 추가·계좌 해제 후 세션 재확인과 재진입에서도 관심과 초기 설정 상태를 유지한다', async () => {
  const server = createFakeServer();
  const state = myMember(server, { connected: true });
  server.on('GET', '/api/v1/auth/session', () => json(member()));
  const { user, router } = open();
  const results = await search(user);
  await user.click(
    within(results).getByRole('button', { name: '삼성전자 관심 추가' }),
  );
  await waitFor(() =>
    expect(state.settings.watchlistIds).toEqual(['cmp-samsung']),
  );
  await waitFor(async () =>
    expect((await watch()).textContent).not.toContain('저장 중'),
  );
  await user.click(await screen.findByRole('button', { name: '연결 끊기' }));
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: '연결 끊기',
    }),
  );
  await screen.findByText('연결 안 됨');
  expect(state.settings.completed).toBe(true);
  expect(state.settings.watchlistIds).toEqual(['cmp-samsung']);
  await act(async () => {
    await router.navigate('/away');
  });
  await act(async () => {
    await loadSession(true);
    await router.navigate('/my');
  });
  await screen.findByRole('button', { name: '삼성전자 관심 종목에서 빼기' });
  expect(screen.getByText('연결 안 됨')).toBeTruthy();
  expect(useAuthStore.getState().onboardingCompleted).toBe(true);
});
