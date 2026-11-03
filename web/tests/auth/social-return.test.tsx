import { StrictMode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import LoginPage from '@/pages/auth/login/LoginPage';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';
import userEvent from '@testing-library/user-event';

const key = 'zoop.auth.socialReturn';
const anonymous: Session = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};
const member = (completed = true): Session => ({
  authenticated: true,
  kind: 'member',
  user: {
    id: 'synthetic-member',
    email: 'member@example.test',
    displayName: '합성 회원',
  },
  setup: { completed, tutorialCompleted: false },
  csrfToken: 'synthetic-csrf',
  expiresAt: null,
});
let current: Session;
let server: ReturnType<typeof createFakeServer>;
function Destination() {
  const l = useLocation();
  return (
    <output data-testid="destination">
      {l.pathname}
      {l.search}
      {l.hash}
    </output>
  );
}
function open(
  entry: string | { pathname: string; state: object } = '/login?social=success',
) {
  return render(
    <StrictMode>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<Destination />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/my" element={<Destination />} />
            <Route path="/onboarding" element={<Destination />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </StrictMode>,
  );
}
beforeEach(() => {
  current = anonymous;
  useAuthStore.getState().clearSession();
  useAuthStore.setState({ status: 'checking' });
  server = createFakeServer();
  server.on('GET', '/api/v1/auth/session', () => json(current));
  server.on('GET', '/api/v1/auth/social/providers', () =>
    json({ items: [{ id: 'google', name: 'Google' }], nextCursor: null }),
  );
  server.on('GET', '/api/v1/me/settings', () => json({ watchlistIds: [] }));
  server.on('GET', '/api/v1/portfolio', () => json({ holdings: [] }));
});
afterEach(() => vi.restoreAllMocks());
async function clickSocial() {
  const link = await screen.findByRole('link', { name: '구글 로그인' });
  // Exercise React's click handler without navigating to a real provider in JSDOM.
  link.addEventListener('click', (e) => e.preventDefault(), { once: true });
  fireEvent.click(link);
}
test('D-AUT-01 A5 saves the exact protected URL before social authorization', async () => {
  open('/my?source=social#watchlist');
  await clickSocial();
  expect(sessionStorage.getItem(key)).toBe('/my?source=social#watchlist');
  expect(
    screen.getByRole('link', { name: '구글 로그인' }).getAttribute('href'),
  ).toBe('/api/v1/auth/social/google/authorize?returnTo=%2Flogin');
});
test('D-AUT-01 A5 removes a previous attempt when social login has no from', async () => {
  sessionStorage.setItem(key, '/my?old=1');
  open('/login');
  await clickSocial();
  expect(sessionStorage.getItem(key)).toBeNull();
});
test('D-AUT-01 A5 leaves storage untouched when a busy session check blocks the social click', async () => {
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/auth/session', () => pending.promise);
  sessionStorage.setItem(key, '/my?old=1');
  const view = open({
    pathname: '/login',
    state: { from: { pathname: '/my', search: '?new=1' } },
  });
  await clickSocial();
  expect(sessionStorage.getItem(key)).toBe('/my?old=1');
  view.unmount();
  pending.resolve(json(anonymous));
});
test.each([true, false])(
  'D-AUT-01 A5 consumes a callback return once, setup completed=%s',
  async (completed) => {
    current = member(completed);
    sessionStorage.setItem(key, '/my?source=social#watchlist');
    open();
    expect((await screen.findByTestId('destination')).textContent).toBe(
      completed ? '/my?source=social#watchlist' : '/onboarding',
    );
    expect(sessionStorage.getItem(key)).toBeNull();
  },
);
test('D-AUT-01 A5 prefers location.state and discards the old saved return', async () => {
  current = member();
  sessionStorage.setItem(key, '/my?old=1');
  open({
    pathname: '/login',
    state: { from: { pathname: '/my', search: '?state=1', hash: '#current' } },
  });
  expect((await screen.findByTestId('destination')).textContent).toBe(
    '/my?state=1#current',
  );
  expect(sessionStorage.getItem(key)).toBeNull();
});
test.each([
  '//evil.example',
  'https://evil.example',
  '/\\evil.example',
  '/login',
  '/signup',
  '/login?retry=1',
  '/signup#terms',
  '/my/../login',
])(
  'D-AUT-01 A5 rejects a stored unsafe or auth destination %s',
  async (from) => {
    current = member();
    sessionStorage.setItem(key, from);
    open();
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=all',
    );
    expect(sessionStorage.getItem(key)).toBeNull();
  },
);
test.each(['cancelled', 'failed', 'email_required', 'link_required'])(
  'D-AUT-01 A5 clears a saved destination on social result %s',
  async (result) => {
    sessionStorage.setItem(key, '/my');
    open(`/login?social=${result}`);
    await screen.findByRole('alert');
    await waitFor(() => expect(sessionStorage.getItem(key)).toBeNull());
  },
);
test.each(['getItem', 'removeItem'] as const)(
  'D-AUT-01 A5 defaults safely when storage %s throws',
  async (method) => {
    current = member();
    sessionStorage.setItem(key, '/my');
    vi.spyOn(Storage.prototype, method).mockImplementation(() => {
      throw new Error('storage unavailable');
    });
    open();
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=all',
    );
  },
);
test('D-AUT-01 A5 retains the consumed return for recovery without reusing storage', async () => {
  current = member();
  sessionStorage.setItem(key, '/my?source=recovery#watchlist');
  server.on('GET', '/api/v1/me/settings', () =>
    apiError(503, 'SOURCE_UNAVAILABLE'),
  );
  open();
  const retry = await screen.findByRole('button', {
    name: '로그인 상태 다시 확인',
  });
  expect(sessionStorage.getItem(key)).toBeNull();
  server.on('GET', '/api/v1/me/settings', () => json({ watchlistIds: [] }));
  await userEvent.click(retry);
  expect((await screen.findByTestId('destination')).textContent).toBe(
    '/my?source=recovery#watchlist',
  );
  expect(sessionStorage.getItem(key)).toBeNull();
});
test('D-AUT-01 A5 does not block social authorization if saving storage throws', async () => {
  open('/my');
  await screen.findByLabelText('이메일');
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('storage unavailable');
  });
  await clickSocial();
  expect(
    screen
      .getByRole('link', { name: '구글 로그인' })
      .getAttribute('aria-disabled'),
  ).toBe('false');
});
test.each([
  '/?mode=personal&scope=watchlist',
  '/?mode=all&select=node%3Afixture#map',
])(
  'D-AUT-01 A5 retains the existing A4 map-return policy for %s',
  async (from) => {
    current = member();
    sessionStorage.setItem(key, from);
    open();
    expect((await screen.findByTestId('destination')).textContent).toBe(
      from.includes('personal') ? '/?mode=all' : from,
    );
  },
);
