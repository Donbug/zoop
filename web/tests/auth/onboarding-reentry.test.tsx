import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test } from 'vitest';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigationType,
  useNavigate,
} from 'react-router-dom';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import MapEntryRoute from '@/components/auth/MapEntryRoute';
import OnboardingLayout from '@/components/onboarding/OnboardingLayout';
import WatchlistSetupPage from '@/pages/onboarding/watchlist/WatchlistSetupPage';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Session } from '@/types/auth';
import { createFakeServer, deferred, json } from '../support/fakeServer';

const member = (completed: boolean): Session => ({
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
beforeEach(() => {
  useAuthStore.getState().setSession(member(true));
});
function Destination() {
  const l = useLocation();
  const type = useNavigationType();
  return (
    <output data-testid="destination">
      {l.pathname}
      {l.search}
      {l.hash}|{type}
    </output>
  );
}
function open(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<Destination />} />
        <Route path="/login" element={<p>로그인 화면</p>} />
        <Route element={<ProtectedRoute />}>
          <Route path="/onboarding/*" element={<p>초기 설정 화면</p>} />
          <Route path="/my" element={<p>내 종목 화면</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

test('D-ONB-01 A6 guards a new entry even after the old unfinished entry completes', async () => {
  useAuthStore.getState().setSession(member(false));
  function Step() {
    const navigate = useNavigate();
    return (
      <button onClick={() => navigate('/onboarding/account')}>다시 진입</button>
    );
  }
  render(
    <MemoryRouter initialEntries={['/onboarding']}>
      <Routes>
        <Route path="/" element={<Destination />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/onboarding/*" element={<Step />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  act(() => useAuthStore.setState({ onboardingCompleted: true }));
  // Existing unfinished entry may finish its own navigation, but cannot grant
  // a permanent bypass to subsequent onboarding visits in the same guard.
  await userEvent.click(screen.getByRole('button', { name: '다시 진입' }));
  expect((await screen.findByTestId('destination')).textContent).toBe(
    '/?mode=all|REPLACE',
  );
});

test('D-ONB-01 A6 does not carry an unfinished entry across a member change', () => {
  useAuthStore.getState().setSession(member(false));
  open('/onboarding');
  act(() =>
    useAuthStore.getState().setSession({
      ...member(true),
      user: {
        id: 'another-member',
        email: 'another@example.test',
        displayName: '다른 합성 회원',
      },
    }),
  );
  expect(screen.getByTestId('destination').textContent).toBe(
    '/?mode=all|REPLACE',
  );
});

test('D-ONB-01 A6 redirects after unknown setup resolves to completed', () => {
  useAuthStore.setState({ onboardingCompleted: null });
  open('/onboarding');
  act(() => useAuthStore.setState({ onboardingCompleted: true }));
  expect(screen.getByTestId('destination').textContent).toBe(
    '/?mode=all|REPLACE',
  );
});
test.each(
  ['/onboarding', '/onboarding/account', '/onboarding/watchlist'].flatMap(
    (path) => [false, true].map((checking) => ({ path, checking })),
  ),
)(
  'D-ONB-01/02 D-WAT-01 A6 replaces completed onboarding entry $path (checking=$checking)',
  ({ path, checking }) => {
    if (checking) useAuthStore.setState({ status: 'checking' });
    open(path);
    expect(screen.getByTestId('destination').textContent).toBe(
      '/?mode=all|REPLACE',
    );
    expect(screen.queryByText('초기 설정 화면')).toBeNull();
  },
);
test.each([false, true])(
  'D-ONB-01 A6 preserves incomplete and unknown setup guards (checking=%s)',
  (checking) => {
    useAuthStore.getState().setSession(member(false));
    if (checking) useAuthStore.setState({ status: 'checking' });
    const view = open('/onboarding/account');
    expect(screen.getByText('초기 설정 화면')).toBeTruthy();
    view.unmount();
    useAuthStore.setState({ onboardingCompleted: null });
    open('/onboarding');
    expect(screen.getByText('초기 설정 화면')).toBeTruthy();
  },
);
test('D-ONB-01 A6 keeps incomplete members out of other protected screens', () => {
  useAuthStore.getState().setSession(member(false));
  open('/my');
  expect(screen.getByText('초기 설정 화면')).toBeTruthy();
  expect(screen.queryByText('내 종목 화면')).toBeNull();
});
test('D-ONB-01 A6 retains the existing guest login redirect', () => {
  useAuthStore
    .getState()
    .setSession({ ...member(true), kind: 'guest', user: null });
  open('/onboarding');
  expect(screen.getByText('로그인 화면')).toBeTruthy();
  expect(screen.queryByTestId('destination')).toBeNull();
});
test('D-ONB-01 A6 leaves completed members on /my', () => {
  open('/my');
  expect(screen.getByText('내 종목 화면')).toBeTruthy();
});
test.each([false, true])(
  'D-WAT-01 A6 preserves final save navigation and social result forwarding (tutorialCompleted=%s)',
  async (tutorialCompleted) => {
    useAuthStore.getState().setSession(member(false));
    const server = createFakeServer();
    const settings = {
      mode: null,
      watchlistIds: [],
      completed: false,
      tutorialCompleted,
      investor: false,
      version: 3,
      metadata: {},
    };
    server.on('GET', '/api/v1/me/settings', () => json(settings));
    server.on('GET', '/api/v1/portfolio', () =>
      json({
        connected: false,
        connection: null,
        holdings: [],
        mockAsOf: null,
        valuation: null,
        metadata: {},
      }),
    );
    const saving = deferred<Response>();
    server.on('PUT', '/api/v1/me/settings', () => saving.promise);
    render(
      <MemoryRouter initialEntries={['/?social=linked']}>
        <Routes>
          <Route element={<MapEntryRoute />}>
            <Route path="/" element={<Destination />} />
          </Route>
          <Route element={<ProtectedRoute />}>
            <Route path="/onboarding" element={<OnboardingLayout />}>
              <Route index element={<WatchlistSetupPage />} />
              <Route path="watchlist" element={<WatchlistSetupPage />} />
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('소셜 계정을 연결했어요.')).toBeTruthy();
    const button = await screen.findByRole('button', {
      name: '고르지 않고 지도 보기',
    });
    await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false));
    await userEvent.click(button);
    expect(
      await screen.findByRole('button', { name: '저장 중…' }),
    ).toBeTruthy();
    expect(screen.queryByTestId('destination')).toBeNull();
    saving.resolve(json({ ...settings, completed: true }));
    expect((await screen.findByTestId('destination')).textContent).toBe(
      tutorialCompleted ? '/?mode=all|REPLACE' : '/?mode=all&tour=1|REPLACE',
    );
    expect(useAuthStore.getState().onboardingCompleted).toBe(true);
    expect(server.calls('PUT', '/api/v1/me/settings')).toHaveLength(1);
  },
);
