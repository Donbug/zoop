import { screen } from '@testing-library/react';
import { beforeEach, expect, test } from 'vitest';
import { useAuthStore } from '@/stores/useAuthStore';
import MyStocksPage from '@/pages/my/MyStocksPage';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  deferred,
  noContent,
} from '../support/fakeServer';
import { myMember } from '../support/myMember';
import { renderRoutes } from '../support/renderRoutes';

// D-MY-01 FS007: logout leaves only the login route and exposes retry on failure.
const currentMember: Session = {
  authenticated: true,
  kind: 'member',
  user: {
    id: 'synthetic-member',
    email: 'member@example.test',
    displayName: '합성 회원',
  },
  setup: { completed: true, tutorialCompleted: false },
  csrfToken: 'synthetic-csrf',
  expiresAt: null,
};

beforeEach(() => {
  useAuthStore.getState().clearSession();
  useAuthStore.getState().setSession(currentMember);
});

function openMy() {
  return renderRoutes(
    [
      { path: '/my', element: <MyStocksPage /> },
      { path: '/login', element: <h1>로그인</h1> },
    ],
    '/my',
  );
}

test('D-MY-01 logout failure keeps personal session and retries to the login screen on success', async () => {
  const server = createFakeServer();
  myMember(server);
  let attempts = 0;
  server.on('POST', '/api/v1/auth/logout', () => {
    attempts += 1;
    return attempts === 1 ? apiError(503, 'SOURCE_UNAVAILABLE') : noContent();
  });
  const { user, location } = openMy();

  await user.click(await screen.findByRole('button', { name: '로그아웃' }));
  expect((await screen.findByRole('alert')).textContent).toContain(
    '로그아웃하지 못했어요. 다시 시도해 주세요.',
  );
  expect(useAuthStore.getState().member?.id).toBe('synthetic-member');
  expect(location()).toBe('/my');

  await user.click(screen.getByRole('button', { name: '로그아웃 다시 시도' }));
  expect(await screen.findByRole('heading', { name: '로그인' })).toBeTruthy();
  expect(location()).toBe('/login');
  expect(useAuthStore.getState().member).toBeNull();
  expect(server.calls('POST', '/api/v1/auth/logout')).toHaveLength(2);
});

test('D-MY-01 logout shows a pending state and sends only one request', async () => {
  const server = createFakeServer();
  myMember(server);
  const response = deferred<Response>();
  server.on('POST', '/api/v1/auth/logout', () => response.promise);
  const { user } = openMy();

  await user.click(await screen.findByRole('button', { name: '로그아웃' }));

  const pending = await screen.findByRole('button', { name: '로그아웃 중…' });
  expect((pending as HTMLButtonElement).disabled).toBe(true);
  expect(server.calls('POST', '/api/v1/auth/logout')).toHaveLength(1);

  response.resolve(noContent());
  expect(await screen.findByRole('heading', { name: '로그인' })).toBeTruthy();
  expect(server.calls('POST', '/api/v1/auth/logout')).toHaveLength(1);
});
