import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { call, sessionNavigation } from '@/apis/auth/ApiService';
import LoginPage from '@/pages/auth/login/LoginPage';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  json,
  noContent,
} from '../support/fakeServer';

// D-AUT-01 · design-direction 5.1: an open session answered with MEMBER_BLOCKED
// is logged out, private state is cleared, and the start screen explains why.
const member: Session = {
  authenticated: true,
  kind: 'member',
  user: {
    id: 'synthetic-a',
    email: 'synthetic@example.test',
    displayName: '합성',
  },
  setup: { completed: true, tutorialCompleted: false },
  csrfToken: 'synthetic-csrf',
  expiresAt: null,
};
const anonymous: Session = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};

let server: ReturnType<typeof createFakeServer>;
const toBlockedNotice = vi.fn();
const original = sessionNavigation.toBlockedNotice;
beforeEach(() => {
  server = createFakeServer();
  useAuthStore.getState().setSession(member);
  sessionNavigation.toBlockedNotice = toBlockedNotice;
  toBlockedNotice.mockClear();
});
afterEach(() => {
  sessionNavigation.toBlockedNotice = original;
});

test('a blocked response during use logs out first, clears private state, then opens the notice', async () => {
  let memberAtLogout: string | null | undefined;
  server.on('GET', '/api/v1/me/settings', () =>
    apiError(403, 'MEMBER_BLOCKED'),
  );
  server.on('POST', '/api/v1/auth/logout', () => {
    // The CSRF-bound session must still be present when the logout is sent.
    memberAtLogout = useAuthStore.getState().member?.id;
    return noContent();
  });
  useOnboardingStore.getState().setWatchlistName('KRX:005930', '삼성전자');

  await expect(call('/api/v1/me/settings', 'GET')).rejects.toMatchObject({
    code: 'MEMBER_BLOCKED',
  });

  expect(memberAtLogout).toBe('synthetic-a');
  expect(server.calls('POST', '/api/v1/auth/logout')).toHaveLength(1);
  expect(useAuthStore.getState().member).toBeNull();
  expect(useOnboardingStore.getState().watchlistNames).toEqual({});
  expect(toBlockedNotice).toHaveBeenCalledTimes(1);
});

test('still clears and notifies when the logout request itself fails', async () => {
  server.on('GET', '/api/v1/me/settings', () =>
    apiError(401, 'MEMBER_BLOCKED'),
  );
  server.on('POST', '/api/v1/auth/logout', () =>
    apiError(403, 'MEMBER_BLOCKED'),
  );
  await expect(call('/api/v1/me/settings', 'GET')).rejects.toMatchObject({
    code: 'MEMBER_BLOCKED',
  });
  expect(useAuthStore.getState().member).toBeNull();
  expect(toBlockedNotice).toHaveBeenCalledTimes(1);
});

test('login and admin requests keep their own inline blocked handling', async () => {
  server.on('POST', '/api/v1/auth/login', () =>
    apiError(403, 'MEMBER_BLOCKED'),
  );
  server.on('POST', '/api/v1/admin/auth/login', () =>
    apiError(403, 'MEMBER_BLOCKED'),
  );
  await expect(
    call('/api/v1/auth/login', 'POST', {}, { skipAuth: true }),
  ).rejects.toMatchObject({ code: 'MEMBER_BLOCKED' });
  await expect(
    call('/api/v1/admin/auth/login', 'POST', {}, { skipAuth: true }),
  ).rejects.toMatchObject({ code: 'MEMBER_BLOCKED' });
  expect(server.calls('POST', '/api/v1/auth/logout')).toHaveLength(0);
  expect(useAuthStore.getState().member?.id).toBe('synthetic-a');
  expect(toBlockedNotice).not.toHaveBeenCalled();
});

test('the start screen explains a blocked logout', async () => {
  useAuthStore.getState().clearSession();
  server.on('GET', '/api/v1/auth/session', () => json(anonymous));
  render(
    <MemoryRouter initialEntries={['/login?notice=blocked']}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect((await screen.findByRole('alert')).textContent).toBe(
    '이용이 제한된 계정이라 로그아웃했어요. 고객센터로 문의해 주세요.',
  );
});
