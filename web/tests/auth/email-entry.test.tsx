import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import SignupPage from '@/pages/auth/signup/SignupPage';
import LoginPage from '@/pages/auth/login/LoginPage';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import { useAuthStore } from '@/stores/useAuthStore';
import { acceptMemberSession, loadSession } from '@/apis/auth/member-session';
import { call } from '@/apis/auth/ApiService';
import {
  createFakeServer,
  json,
  apiError,
  deferred,
} from '../support/fakeServer';
import type { MemberSession } from '@/types/auth/session';

// All identities, credentials and cookie values in these tests are synthetic.
const email = 'member@example.test';
const password = ' synthetic password 000000 ';
const anonymous: MemberSession = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};
const member = (completed = false): MemberSession => ({
  authenticated: true,
  kind: 'member',
  user: { id: 'synthetic-member', email, displayName: '가상 회원' },
  setup: { completed, tutorialCompleted: false },
  csrfToken: 'synthetic-csrf',
  expiresAt: '2099-01-01T00:00:00Z',
});
const terms = [
  {
    id: 'service',
    title: '서비스 이용약관',
    required: true,
    body: '승인된 합성 이용약관',
    version: 'v1',
    bodyAvailable: true,
  },
  {
    id: 'privacy',
    title: '개인정보 수집·이용 동의',
    required: true,
    body: '승인된 합성 개인정보 약관',
    version: 'v2',
    bodyAvailable: true,
  },
];
let server: ReturnType<typeof createFakeServer>;
let current: MemberSession;
beforeEach(() => {
  const rev = useAuthStore.getState().sessionRevision;
  useAuthStore.setState({
    member: null,
    onboardingCompleted: null,
    session: null,
    status: 'checking',
    sessionRevision: rev + 1,
  });
  current = anonymous;
  server = createFakeServer();
  server.on('GET', '/api/v1/auth/session', () => json(current));
  server.on('GET', '/api/v1/auth/terms', () =>
    json({ items: terms, nextCursor: null }),
  );
  server.on('POST', '/api/v1/auth/signup', () => {
    current = member();
    return json(current, 201);
  });
  server.on('POST', '/api/v1/auth/login', () => {
    current = member();
    return json(current);
  });
  server.on('GET', '/api/v1/me/settings', () =>
    json({ watchlistIds: [], metadata: { partial: false } }),
  );
  server.on('GET', '/api/v1/portfolio', () =>
    json({ holdings: [], metadata: { partial: false } }),
  );
});
function Destination() {
  const l = useLocation();
  return (
    <output data-testid="destination">
      {l.pathname}
      {l.search}
    </output>
  );
}
function open(path = '/signup') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/onboarding" element={<Destination />} />
          <Route path="/my" element={<Destination />} />
        </Route>
        <Route path="/" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
}
async function fillSignup() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('이메일'), email);
  await user.type(screen.getByLabelText('비밀번호'), password);
  await screen.findByLabelText('모두 동의');
  await user.click(screen.getByLabelText('모두 동의'));
  return user;
}
async function login() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('이메일'), email);
  await user.type(screen.getByLabelText('비밀번호'), password);
  await user.click(screen.getByRole('button', { name: '로그인' }));
  return user;
}
describe('Issue35 · FS003 D-AUT-02', () => {
  it('blocks missing fields, invalid email, and missing required consent', async () => {
    open();
    await screen.findByLabelText('모두 동의');
    await userEvent.click(
      screen.getByRole('button', { name: '가입하고 시작하기' }),
    );
    expect(
      await screen.findByText('이메일과 비밀번호를 입력해 주세요.'),
    ).toBeTruthy();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('이메일'), 'wrong');
    await user.type(screen.getByLabelText('비밀번호'), password);
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect(
      await screen.findByText('올바른 이메일 형식을 입력해 주세요.'),
    ).toBeTruthy();
    await user.clear(screen.getByLabelText('이메일'));
    await user.type(screen.getByLabelText('이메일'), email);
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect(await screen.findByText('필수 약관에 동의해 주세요.')).toBeTruthy();
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(0);
  });
  it.each([
    ['7 ASCII characters', 'aB3!xY7'],
    ['33 ASCII characters', 'A7!b'.repeat(8) + 'x'],
    ['7 Unicode code points', '🦊'.repeat(7)],
    ['33 Unicode code points', '🦊'.repeat(33)],
  ])('blocks %s before sending', async (_label, input) => {
    open();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('이메일'), email);
    await user.type(screen.getByLabelText('비밀번호'), input);
    await user.click(await screen.findByLabelText('모두 동의'));
    expect(
      screen.getByText(/8자 이상 32자 이하로 입력해 주세요. 공백은 그대로/),
    ).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect(
      await screen.findByText('비밀번호는 8자 이상 32자 이하로 입력해 주세요.'),
    ).toBeTruthy();
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(0);
  });
  it.each([
    ['8 ASCII characters', 'abCD!567'],
    ['14 ASCII characters', 'abCD!567xyz123'],
    ['32 ASCII characters', 'A7!b'.repeat(8)],
    ['8 Unicode code points', '🦊'.repeat(8)],
    ['32 Unicode code points', '🦊'.repeat(32)],
    ['8 characters including surrounding spaces', ' aB3!xY '],
  ])('submits %s without changing the password', async (_label, input) => {
    open();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('이메일'), email);
    await user.type(screen.getByLabelText('비밀번호'), input);
    await user.click(await screen.findByLabelText('모두 동의'));
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await screen.findByTestId('destination');
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(1);
    expect(server.calls('POST', '/api/v1/auth/signup')[0].body).toMatchObject({
      password: input,
    });
  });
  it('explains the current policy when the server rejects a common password', async () => {
    server.on('POST', '/api/v1/auth/signup', () =>
      apiError(422, 'INVALID_REQUEST'),
    );
    open();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('이메일'), email);
    await user.type(screen.getByLabelText('비밀번호'), 'password');
    await user.click(await screen.findByLabelText('모두 동의'));
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect(
      await screen.findByText(
        '입력한 가입 정보를 확인해 주세요. 비밀번호는 8자 이상 32자 이하이며 제어 문자와 흔한 비밀번호는 쓸 수 없어요.',
      ),
    ).toBeTruthy();
    expect(screen.queryByTestId('destination')).toBeNull();
  });
  it('sends actual term versions and preserves password spaces, verifies session, opens onboarding', async () => {
    open();
    const user = await fillSignup();
    await user.type(screen.getByLabelText('표시 이름 (선택)'), ' 이름 ');
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/onboarding',
    );
    expect(server.calls('POST', '/api/v1/auth/signup')[0].body).toEqual({
      email,
      password,
      displayName: '이름',
      agreements: [
        { id: 'service', version: 'v1', accepted: true },
        { id: 'privacy', version: 'v2', accepted: true },
      ],
    });
    expect(server.calls('GET', '/api/v1/auth/session')).toHaveLength(2);
    expect(server.requests.some((r) => r.path.includes('refresh'))).toBe(false);
    expect(useAuthStore.getState().member?.id).toBe('synthetic-member');
  });
  it('reads all terms pages before allowing consent to complete', async () => {
    server.on('GET', '/api/v1/auth/terms', (r) =>
      json(
        r.query.has('cursor')
          ? { items: [terms[1]], nextCursor: null }
          : { items: [terms[0]], nextCursor: 'page2' },
      ),
    );
    open();
    const user = await fillSignup();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await screen.findByTestId('destination');
    expect(server.calls('GET', '/api/v1/auth/terms')).toHaveLength(2);
    expect(
      (
        server.calls('POST', '/api/v1/auth/signup')[0].body as {
          agreements: unknown[];
        }
      ).agreements,
    ).toHaveLength(2);
  });
  it.each(['empty', 'missing-body'] as const)(
    'blocks unavailable terms: %s',
    async (scenario) => {
      server.on('GET', '/api/v1/auth/terms', () =>
        json({
          items:
            scenario === 'empty'
              ? []
              : [
                  {
                    ...terms[0],
                    body: null,
                    version: null,
                    bodyAvailable: false,
                  },
                ],
          nextCursor: null,
        }),
      );
      open();
      expect(
        await screen.findByText('가입에 필요한 약관 본문이 준비되지 않았어요.'),
      ).toBeTruthy();
      expect(
        screen
          .getByRole('button', { name: '가입하고 시작하기' })
          .hasAttribute('disabled'),
      ).toBe(true);
      expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(0);
    },
  );
  it('recovers terms lookup failure and renders body as text', async () => {
    server.on('GET', '/api/v1/auth/terms', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    open();
    await screen.findByText('약관을 불러오지 못했어요.');
    server.on('GET', '/api/v1/auth/terms', () =>
      json({
        items: [
          { ...terms[0], body: '<script>synthetic text</script>' },
          terms[1],
        ],
        nextCursor: null,
      }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '약관 다시 조회' }),
    );
    await screen.findByLabelText('모두 동의');
    expect(document.querySelector('[data-term-id] script')).toBeNull();
    expect(screen.getByText('<script>synthetic text</script>')).toBeTruthy();
  });
  it('shows duplicate email and can retry after correcting it', async () => {
    server.on('POST', '/api/v1/auth/signup', () =>
      apiError(409, 'EMAIL_TAKEN'),
    );
    open();
    const user = await fillSignup();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await screen.findByText(/이미 가입된 이메일/);
    expect(screen.queryByTestId('destination')).toBeNull();
    server.on('POST', '/api/v1/auth/signup', () => {
      current = member();
      return json(current, 201);
    });
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/onboarding',
    );
  });
  it('new terms invalidate old consent before another signup attempt', async () => {
    server.on('POST', '/api/v1/auth/signup', () =>
      apiError(422, 'TERMS_REQUIRED'),
    );
    open();
    const user = await fillSignup();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await screen.findByRole('button', { name: '약관 새로 확인' });
    server.on('GET', '/api/v1/auth/terms', () =>
      json({
        items: terms.map((t) => ({ ...t, version: 'new-version' })),
        nextCursor: null,
      }),
    );
    await user.click(screen.getByRole('button', { name: '약관 새로 확인' }));
    await waitFor(() =>
      expect(
        (screen.getByLabelText('모두 동의') as HTMLInputElement).checked,
      ).toBe(false),
    );
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(1);
  });
  it('locks all fields and prevents repeated signup while pending', async () => {
    const response = deferred<Response>();
    server.on('POST', '/api/v1/auth/signup', () => response.promise);
    open();
    const user = await fillSignup();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect(screen.getByLabelText('이메일').hasAttribute('disabled')).toBe(true);
    expect(screen.queryByRole('link', { name: /시작 화면으로/ })).toBeNull();
    await user.click(
      screen.getByRole('button', { name: /가입과 로그인 상태/ }),
    );
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(1);
    current = member();
    await act(async () => response.resolve(json(current, 201)));
    await screen.findByTestId('destination');
  });
  it('confirmation retry after a successful signup never posts signup twice', async () => {
    let reads = 0;
    server.on('GET', '/api/v1/auth/session', () =>
      ++reads === 2 ? apiError(503, 'SOURCE_UNAVAILABLE') : json(current),
    );
    open();
    const user = await fillSignup();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await screen.findByRole('button', { name: '가입 상태 다시 확인' });
    await user.click(
      screen.getByRole('button', { name: '가입 상태 다시 확인' }),
    );
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/onboarding',
    );
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(1);
  });
  it('recovers unknown signup outcome by session lookup without re-posting', async () => {
    server.on('POST', '/api/v1/auth/signup', () => {
      current = member();
      throw new Error('synthetic disconnected response');
    });
    open();
    const user = await fillSignup();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await user.click(
      await screen.findByRole('button', { name: '가입 상태 다시 확인' }),
    );
    await screen.findByTestId('destination');
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(1);
  });
  it('does not restore a stale signup session after another member takes over', async () => {
    const response = deferred<Response>();
    server.on('POST', '/api/v1/auth/signup', () => response.promise);
    open();
    const user = await fillSignup();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await act(async () =>
      acceptMemberSession({
        ...member(),
        user: {
          id: 'different-member',
          email: 'different@example.test',
          displayName: '다른 가상 회원',
        },
      }),
    );
    await act(async () => response.resolve(json(member(), 201)));
    expect(useAuthStore.getState().member?.id).toBe('different-member');
    expect(screen.queryByTestId('destination')).toBeNull();
  });
  it('does not navigate when its page has unmounted before a signup response', async () => {
    const response = deferred<Response>();
    server.on('POST', '/api/v1/auth/signup', () => response.promise);
    const view = open();
    const user = await fillSignup();
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    view.unmount();
    await act(async () => response.resolve(json(member(), 201)));
    expect(useAuthStore.getState().member).toBeNull();
  });
});
describe('Issue35 · FS006 D-AUT-01/D-ONB-01', () => {
  it.each([
    { holdings: [], watchlistIds: [], mode: 'all' },
    { holdings: [{}], watchlistIds: [], mode: 'personal' },
    { holdings: [], watchlistIds: ['synthetic-company'], mode: 'personal' },
  ])(
    'completed login chooses $mode from known holdings/interests',
    async ({ holdings, watchlistIds, mode }) => {
      server.on('POST', '/api/v1/auth/login', () => {
        current = member(true);
        return json(current);
      });
      server.on('GET', '/api/v1/me/settings', () => json({ watchlistIds }));
      server.on('GET', '/api/v1/portfolio', () => json({ holdings }));
      open('/login');
      await login();
      expect((await screen.findByTestId('destination')).textContent).toBe(
        `/?mode=${mode}`,
      );
    },
  );
  it('incomplete login opens onboarding, not an arbitrary return URL', async () => {
    open('/login');
    await login();
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/onboarding',
    );
  });
  it('login 401 stays on form and never calls JWT refresh', async () => {
    server.on('POST', '/api/v1/auth/login', () =>
      apiError(401, 'INVALID_CREDENTIALS'),
    );
    open('/login');
    await login();
    await screen.findByText(/이메일 또는 비밀번호가 맞지 않아요/);
    expect(screen.queryByTestId('destination')).toBeNull();
    expect(server.requests.some((r) => r.path.includes('refresh'))).toBe(false);
  });
  it('does not turn failed or partial portfolio into an empty-market destination', async () => {
    server.on('POST', '/api/v1/auth/login', () => {
      current = member(true);
      return json(current);
    });
    server.on('GET', '/api/v1/portfolio', () =>
      json({ holdings: [], metadata: { partial: true } }),
    );
    open('/login');
    const user = await login();
    await screen.findByRole('button', { name: '로그인 상태 다시 확인' });
    expect(screen.queryByTestId('destination')).toBeNull();
    server.on('GET', '/api/v1/portfolio', () => json({ holdings: [{}] }));
    await user.click(
      screen.getByRole('button', { name: '로그인 상태 다시 확인' }),
    );
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=personal',
    );
    expect(server.calls('POST', '/api/v1/auth/login')).toHaveLength(1);
  });
  it('does not trust a forged local access token for protected routes', async () => {
    localStorage.setItem('accessToken', 'synthetic-forged-token');
    open('/my');
    expect(
      await screen.findByRole('heading', { name: '이메일로 로그인' }),
    ).toBeTruthy();
    expect(screen.queryByTestId('destination')).toBeNull();
  });
  it('session lookup failure offers retry without guessing anonymous/member', async () => {
    server.on('GET', '/api/v1/auth/session', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    open('/my');
    await screen.findByText('로그인 상태를 확인하지 못했어요.');
    expect(
      screen.queryByRole('heading', { name: '이메일로 로그인' }),
    ).toBeNull();
    current = member();
    server.on('GET', '/api/v1/auth/session', () => json(current));
    await userEvent.click(
      screen.getByRole('button', { name: '세션 다시 확인' }),
    );
    expect((await screen.findByTestId('destination')).textContent).toBe('/my');
  });
  it('cookie authentication reaches protected content with no bearer token', async () => {
    current = member();
    open('/my');
    expect((await screen.findByTestId('destination')).textContent).toBe('/my');
    expect(useAuthStore.getState().session?.kind).toBe('member');
  });
  it('cookie API writes include CSRF and cookies without Authorization', async () => {
    acceptMemberSession(member());
    let init: RequestInit | undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url, options) => {
        init = options;
        return json({ ok: true });
      }),
    );
    await call('/api/v1/me/settings', 'PUT', { version: 1 });
    expect(init?.credentials).toBe('include');
    expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe(
      'synthetic-csrf',
    );
    expect(new Headers(init?.headers).has('Authorization')).toBe(false);
  });
  it('discards a stale session read after session invalidation', async () => {
    const response = deferred<Response>();
    server.on('GET', '/api/v1/auth/session', () => response.promise);
    const request = loadSession(true).catch(() => null);
    useAuthStore.getState().clearSession();
    response.resolve(json(member()));
    await request;
    expect(useAuthStore.getState().member).toBeNull();
  });
});
