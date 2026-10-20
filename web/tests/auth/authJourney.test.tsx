import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import LoginPage from '@/pages/auth/login/LoginPage';
import SignupPage from '@/pages/auth/signup/SignupPage';
import MyStocksPage from '@/pages/my/MyStocksPage';
import AppLayout from '@/components/common/AppLayout';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import { call } from '@/apis/auth/ApiService';
import { logout } from '@/apis/auth/auth';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import { useAiChatStore } from '@/stores/useAiChatStore';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  noContent,
} from '../support/fakeServer';
import { myMember } from '../support/myMember';

// #36 / WBS 6.2.8 · D-AUT-01/02 → ProtectedRoute → D-MY-01.
// Real pages, auth hooks, transport and private stores; only the HTTP producer is synthetic.
const anonymous: Session = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};
const member = (id = 'journey-a', completed = true): Session => ({
  authenticated: true,
  kind: 'member',
  user: { id, email: `${id}@example.test`, displayName: `합성 ${id}` },
  setup: { completed, tutorialCompleted: false },
  csrfToken: `synthetic-csrf-${id}`,
  expiresAt: '2099-01-01T00:00:00Z',
});
const terms = [
  {
    id: 'service',
    title: '합성 필수 약관',
    required: true,
    body: '통합 검증용 약관',
    version: 'fixture-v1',
    bodyAvailable: true,
  },
];
let server: ReturnType<typeof createFakeServer>;
let cookieSession: Session;

function Location() {
  const l = useLocation();
  return (
    <output data-testid="location">
      {l.pathname}
      {l.search}
      {l.hash}
    </output>
  );
}
function open(path: string) {
  const result = render(
    <MemoryRouter initialEntries={[path]}>
      <Location />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/" element={<h1>지도 목적지</h1>} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/my" element={<MyStocksPage />} />
          </Route>
          <Route path="/onboarding" element={<h1>초기 설정 목적지</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  return { ...result, user: userEvent.setup() };
}
async function login(
  user: ReturnType<typeof userEvent.setup>,
  id = 'journey-a',
) {
  await user.type(await screen.findByLabelText('이메일'), `${id}@example.test`);
  await user.type(
    screen.getByLabelText('비밀번호'),
    'synthetic journey pass 2026',
  );
  await user.click(screen.getByRole('button', { name: '로그인' }));
}
const location = () => screen.getByTestId('location').textContent;

beforeEach(() => {
  useAuthStore.getState().clearSession();
  useAuthStore.setState({ status: 'checking' });
  cookieSession = anonymous;
  server = createFakeServer();
  myMember(server);
  server.on('GET', '/api/v1/auth/session', () => json(cookieSession));
  server.on('GET', '/api/v1/auth/social/providers', () =>
    json({
      items: [
        { id: 'google', name: 'Google' },
        { id: 'kakao', name: 'Kakao' },
      ],
      nextCursor: null,
    }),
  );
  server.on('GET', '/api/v1/auth/terms', () =>
    json({ items: terms, nextCursor: null }),
  );
  server.on('POST', '/api/v1/auth/login', ({ body }) => {
    const id = (body as { email: string }).email.split('@')[0];
    cookieSession = member(id);
    return json(cookieSession);
  });
  server.on('POST', '/api/v1/auth/signup', () => {
    cookieSession = member('new-member', false);
    return json(cookieSession, 201);
  });
  server.on('POST', '/api/v1/auth/social/signup', () => {
    cookieSession = member('social-member', false);
    return json(cookieSession, 201);
  });
  server.on('POST', '/api/v1/auth/logout', () => {
    cookieSession = anonymous;
    return noContent();
  });
});

describe('#36 인증 화면·세션·보호 화면 통합', () => {
  it('returns to the exact protected URL after login, restores the cookie on reload, then revokes logout and clears private state', async () => {
    const view = open('/my?source=auth-test#watchlist');
    await login(view.user);
    await screen.findByRole('heading', { name: '내 종목' });
    expect(location()).toBe('/my?source=auth-test#watchlist');
    expect(server.calls('POST', '/api/v1/auth/login')).toHaveLength(1);
    const sessionReads = server.calls('GET', '/api/v1/auth/session').length;
    view.unmount();
    // A full page load resets in-memory state, but the server cookie survives.
    useAuthStore.getState().clearSession();
    useAuthStore.setState({ status: 'checking' });
    const reloaded = open('/my?source=auth-test#watchlist');
    await screen.findByRole('heading', { name: '내 종목' });
    expect(server.calls('GET', '/api/v1/auth/session')).toHaveLength(
      sessionReads + 1,
    );
    useOnboardingStore.getState().toggleWatchlist('private-company');
    useAiChatStore.getState().setDraft('이전 회원 질문');
    sessionStorage.setItem('zoop.graph.personal-filter', 'holdings');
    await reloaded.user.click(
      screen.getByRole('button', { name: '계정 메뉴 열기' }),
    );
    await reloaded.user.click(
      screen.getByRole('menuitem', { name: '로그아웃' }),
    );
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    expect(cookieSession.kind).toBe('anonymous');
    expect(useAuthStore.getState().member).toBeNull();
    expect(useOnboardingStore.getState().watchlistIds).toEqual([]);
    expect(useAiChatStore.getState().draft).toBe('');
    expect(sessionStorage.getItem('zoop.graph.personal-filter')).toBeNull();
    const logoutInit = vi
      .mocked(fetch)
      .mock.calls.find(([url]) => String(url).endsWith('/auth/logout'))?.[1];
    expect(logoutInit?.credentials).toBe('include');
    expect(new Headers(logoutInit?.headers).get('X-CSRF-Token')).toBe(
      'synthetic-csrf-journey-a',
    );
    expect(new Headers(logoutInit?.headers).has('Authorization')).toBe(false);
  });

  it('redirects an expired private request to login and returns only after the new session is confirmed', async () => {
    cookieSession = member();
    const { user } = open('/my?from=expiry');
    await screen.findByRole('heading', { name: '내 종목' });
    useOnboardingStore.getState().toggleWatchlist('expired-private');
    server.on('GET', '/api/v1/me/settings', () =>
      apiError(401, 'SESSION_EXPIRED'),
    );
    cookieSession = anonymous;
    await act(async () => {
      await call('/api/v1/me/settings', 'GET').catch(() => undefined);
    });
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    expect(screen.queryByRole('heading', { name: '내 종목' })).toBeNull();
    expect(useOnboardingStore.getState().watchlistIds).toEqual([]);
    myMember(server);
    await login(user, 'journey-b');
    await screen.findByRole('heading', { name: '내 종목' });
    expect(location()).toBe('/my?from=expiry');
    expect(useAuthStore.getState().member?.id).toBe('journey-b');
  });

  it('does not disclose private pages to a guest even with a forged local token', async () => {
    cookieSession = {
      ...anonymous,
      authenticated: true,
      kind: 'guest',
      csrfToken: 'synthetic-guest',
    };
    localStorage.setItem('accessToken', 'synthetic-forged');
    open('/my');
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(0);
    expect(server.calls('GET', '/api/v1/me/settings')).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: '내 종목' })).toBeNull();
  });

  it('recovers a failed session bootstrap without mounting private data early', async () => {
    server.on('GET', '/api/v1/auth/session', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    const { user } = open('/my');
    await screen.findByText('로그인 상태를 확인하지 못했어요.');
    expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(0);
    cookieSession = member();
    server.on('GET', '/api/v1/auth/session', () => json(cookieSession));
    await user.click(screen.getByRole('button', { name: '세션 다시 확인' }));
    await screen.findByRole('heading', { name: '내 종목' });
    expect(server.calls('POST', '/api/v1/auth/login')).toHaveLength(0);
  });

  it('retries only destination reads after successful login, without logging in twice', async () => {
    server.on('GET', '/api/v1/portfolio', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    const { user } = open('/login');
    await login(user);
    await screen.findByRole('button', { name: '로그인 상태 다시 확인' });
    expect(location()).toBe('/login');
    expect(screen.queryByText('지도 목적지')).toBeNull();
    myMember(server);
    await user.click(
      screen.getByRole('button', { name: '로그인 상태 다시 확인' }),
    );
    await screen.findByRole('heading', { name: '지도 목적지' });
    expect(location()).toBe('/?mode=all');
    expect(server.calls('POST', '/api/v1/auth/login')).toHaveLength(1);
  });

  it('finishes email signup with current consent then confirms the cookie before onboarding', async () => {
    const { user } = open('/login');
    await user.click(
      await screen.findByRole('link', { name: '이메일로 회원가입' }),
    );
    await user.type(
      await screen.findByLabelText('이메일'),
      'new-member@example.test',
    );
    await user.type(
      screen.getByLabelText('비밀번호'),
      'synthetic signup pass 2026',
    );
    await user.click(await screen.findByLabelText('모두 동의'));
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await screen.findByRole('heading', { name: '초기 설정 목적지' });
    expect(useAuthStore.getState().member?.id).toBe('new-member');
    expect(server.calls('POST', '/api/v1/auth/signup')[0].body).toMatchObject({
      agreements: [{ id: 'service', version: 'fixture-v1', accepted: true }],
    });
    expect(server.calls('POST', '/api/v1/auth/login')).toHaveLength(0);
  });

  it.each(['google', 'kakao'])(
    'resumes an existing %s member cookie after the provider redirect without another login POST',
    async (provider) => {
      cookieSession = member(`${provider}-member`);
      open('/login');
      await screen.findByRole('heading', { name: '지도 목적지' });
      expect(location()).toBe('/?mode=all');
      expect(useAuthStore.getState().member?.id).toBe(`${provider}-member`);
      expect(server.calls('POST', '/api/v1/auth/login')).toHaveLength(0);
    },
  );

  it('recovers a lost social-signup response by confirming the cookie, never repeats the signup POST', async () => {
    server.on('POST', '/api/v1/auth/social/signup', () => {
      cookieSession = member('social-member', false);
      throw new Error('synthetic response loss');
    });
    const { user } = open('/signup?social=pending');
    await user.click(await screen.findByLabelText('모두 동의'));
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await user.click(
      await screen.findByRole('button', { name: '가입 상태 다시 확인' }),
    );
    await screen.findByRole('heading', { name: '초기 설정 목적지' });
    expect(server.calls('POST', '/api/v1/auth/social/signup')).toHaveLength(1);
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(0);
  });

  it('an old logout cannot erase a newly confirmed member session', async () => {
    cookieSession = member();
    open('/my');
    await screen.findByRole('heading', { name: '내 종목' });
    const pending = deferred<Response>();
    server.on('POST', '/api/v1/auth/logout', () => pending.promise);
    const result = logout();
    await act(async () =>
      useAuthStore.getState().setSession(member('journey-b')),
    );
    await act(async () => {
      pending.resolve(noContent());
      await result;
    });
    expect(useAuthStore.getState().member?.id).toBe('journey-b');
    expect(location()).toBe('/my');
  });

  it('keeps the confirmed member after server logout failure so revocation can be retried', async () => {
    cookieSession = member();
    open('/my');
    await screen.findByRole('heading', { name: '내 종목' });
    server.on('POST', '/api/v1/auth/logout', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    await act(async () => {
      await expect(logout()).rejects.toMatchObject({ status: 503 });
    });
    expect(useAuthStore.getState().member?.id).toBe('journey-a');
    expect(location()).toBe('/my');
  });
  it('shows logout failure, prevents duplicate pending clicks and retries server revocation from the real page', async () => {
    cookieSession = member();
    const { user } = open('/my');
    await screen.findByRole('heading', { name: '내 종목' });
    const pending = deferred<Response>();
    server.on('POST', '/api/v1/auth/logout', () => pending.promise);
    await user.click(screen.getByRole('button', { name: '계정 메뉴 열기' }));
    await user.click(screen.getByRole('menuitem', { name: '로그아웃' }));
    const button = screen.getByRole('menuitem', {
      name: '로그아웃하고 있어요',
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await user.click(button);
    expect(server.calls('POST', '/api/v1/auth/logout')).toHaveLength(1);
    await act(async () => pending.resolve(apiError(503, 'SOURCE_UNAVAILABLE')));
    await screen.findByText(/로그아웃하지 못했어요/);
    expect(location()).toBe('/my');
    expect(useAuthStore.getState().member?.id).toBe('journey-a');
    server.on('POST', '/api/v1/auth/logout', () => {
      cookieSession = anonymous;
      return noContent();
    });
    await user.click(
      screen.getByRole('menuitem', { name: '로그아웃 다시 시도' }),
    );
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    expect(useAuthStore.getState().member).toBeNull();
    expect(cookieSession.kind).toBe('anonymous');
    expect(server.calls('POST', '/api/v1/auth/logout')).toHaveLength(2);
  });

  it('does not show an old logout failure on the next member page', async () => {
    cookieSession = member();
    const { user } = open('/my');
    await screen.findByRole('heading', { name: '내 종목' });
    const pending = deferred<Response>();
    server.on('POST', '/api/v1/auth/logout', () => pending.promise);
    await user.click(screen.getByRole('button', { name: '계정 메뉴 열기' }));
    await user.click(screen.getByRole('menuitem', { name: '로그아웃' }));
    await act(async () =>
      useAuthStore.getState().setSession(member('journey-b')),
    );
    await act(async () => pending.resolve(apiError(503, 'SOURCE_UNAVAILABLE')));
    expect(useAuthStore.getState().member?.id).toBe('journey-b');
    expect(screen.queryByText(/로그아웃하지 못했어요/)).toBeNull();
    await user.click(screen.getByRole('button', { name: '계정 메뉴 열기' }));
    expect(
      (screen.getByRole('menuitem', { name: '로그아웃' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
});
