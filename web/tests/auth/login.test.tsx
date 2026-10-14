import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  type InitialEntry,
} from 'react-router-dom';
import LoginPage from '@/pages/auth/login/LoginPage';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import { call } from '@/apis/auth/ApiService';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';

const metadata = { requestId: 'req-test' };

function session(overrides: Partial<Session> = {}): Session {
  return {
    authenticated: false,
    kind: 'anonymous',
    user: null,
    setup: null,
    csrfToken: null,
    expiresAt: null,
    ...overrides,
  };
}

function memberSession(completed: boolean): Session {
  return session({
    authenticated: true,
    kind: 'member',
    user: {
      id: 'mem-1',
      email: 'member@zoop.test',
      displayName: '테스트 회원',
    },
    setup: { completed, tutorialCompleted: false },
    csrfToken: 'csrf-member',
    expiresAt: '2026-10-15T00:00:00Z',
  });
}

const guestSession = session({
  authenticated: true,
  kind: 'guest',
  setup: { completed: false, tutorialCompleted: false },
  csrfToken: 'csrf-guest',
});

function Destination() {
  const location = useLocation();
  return (
    <output data-testid="destination">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderApp(entry: InitialEntry = '/login') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<Destination />} />
        <Route path="/signup" element={<Destination />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/onboarding" element={<Destination />} />
          <Route path="/my" element={<Destination />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

async function fillAndSubmit(email: string, password: string) {
  const user = userEvent.setup();
  if (email) await user.type(screen.getByLabelText('이메일'), email);
  if (password) await user.type(screen.getByLabelText('비밀번호'), password);
  await user.click(screen.getByRole('button', { name: '로그인' }));
  return user;
}

let server: FakeServer;

beforeEach(() => {
  useAuthStore.setState({
    status: 'checking',
    session: null,
    member: null,
    onboardingCompleted: null,
  });
  server = createFakeServer();
  server.on('GET', '/api/v1/auth/session', () =>
    json({ ...session(), metadata }),
  );
});

describe('D-AUT-01 이메일 로그인 (FS002·FS006)', () => {
  test('초기 설정을 마치지 않은 회원은 로그인 후 초기 설정으로 간다', async () => {
    server.on('POST', '/api/v1/auth/login', () =>
      json({ ...memberSession(false), metadata }),
    );
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await fillAndSubmit(' member@zoop.test ', 'secret-pass');

    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/onboarding',
    );
    expect(server.calls('POST', '/api/v1/auth/login')[0].body).toEqual({
      email: 'member@zoop.test',
      password: 'secret-pass',
    });
    expect(useAuthStore.getState().member?.id).toBe('mem-1');
  });

  test('초기 설정을 마친 회원은 내 종목 지도로 간다', async () => {
    server.on('POST', '/api/v1/auth/login', () =>
      json({ ...memberSession(true), metadata }),
    );
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await fillAndSubmit('member@zoop.test', 'secret-pass');

    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=personal',
    );
  });

  test('보호된 화면에서 왔으면 로그인 후 그 화면으로 돌아간다', async () => {
    server.on('POST', '/api/v1/auth/login', () =>
      json({ ...memberSession(true), metadata }),
    );
    renderApp('/my');
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await fillAndSubmit('member@zoop.test', 'secret-pass');

    expect((await screen.findByTestId('destination')).textContent).toBe('/my');
  });

  test('빈 입력은 요청하지 않고 안내한다', async () => {
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await fillAndSubmit('member@zoop.test', '');

    expect(
      screen.getByText('이메일과 비밀번호를 모두 입력해 주세요.'),
    ).toBeTruthy();
    expect(server.calls('POST', '/api/v1/auth/login')).toHaveLength(0);
  });

  test('인증에 실패하면 머물러 입력을 유지하고, 다시 시도해 성공하면 이동한다', async () => {
    server.on('POST', '/api/v1/auth/login', () =>
      apiError(401, 'INVALID_CREDENTIALS'),
    );
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    const user = await fillAndSubmit('member@zoop.test', 'wrong-pass');

    expect(
      await screen.findByText(
        '이메일 또는 비밀번호가 맞지 않아요. 다시 확인해 주세요.',
      ),
    ).toBeTruthy();
    expect((screen.getByLabelText('이메일') as HTMLInputElement).value).toBe(
      'member@zoop.test',
    );
    expect(screen.queryByTestId('destination')).toBeNull();

    server.on('POST', '/api/v1/auth/login', () =>
      json({ ...memberSession(true), metadata }),
    );
    await user.click(screen.getByRole('button', { name: '로그인' }));
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=personal',
    );
  });

  test('차단 회원과 요청 한도 초과는 각각 안내한다', async () => {
    server.on('POST', '/api/v1/auth/login', () =>
      apiError(403, 'MEMBER_BLOCKED'),
    );
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    const user = await fillAndSubmit('member@zoop.test', 'secret-pass');
    expect(
      await screen.findByText(
        '이용이 제한된 계정이에요. 고객센터로 문의해 주세요.',
      ),
    ).toBeTruthy();

    server.on('POST', '/api/v1/auth/login', () =>
      apiError(429, 'RATE_LIMITED'),
    );
    await user.click(screen.getByRole('button', { name: '로그인' }));
    expect(
      await screen.findByText(
        '로그인 시도가 많아요. 잠시 후 다시 시도해 주세요.',
      ),
    ).toBeTruthy();
  });

  test('로그인 중에는 버튼과 다른 시작 방법을 막는다', async () => {
    const pending = deferred<Response>();
    server.on('POST', '/api/v1/auth/login', () => pending.promise);
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await fillAndSubmit('member@zoop.test', 'secret-pass');

    const submit = await screen.findByRole('button', {
      name: '로그인하고 있어요',
    });
    expect(submit.hasAttribute('disabled')).toBe(true);
    expect(
      screen
        .getByRole('button', { name: '로그인 없이 둘러보기' })
        .hasAttribute('disabled'),
    ).toBe(true);

    pending.resolve(json({ ...memberSession(false), metadata }));
    await screen.findByTestId('destination');
  });

  test('이미 회원 세션이 있으면 로그인 화면을 건너뛴다', async () => {
    server.on('GET', '/api/v1/auth/session', () =>
      json({ ...memberSession(true), metadata }),
    );
    renderApp();
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=personal',
    );
  });
});

describe('D-AUT-01 시작 방법 선택 (FS001·FS005)', () => {
  test('로그인 없이 둘러보면 비회원 세션을 시작하고 시장 전체 지도로 간다', async () => {
    server.on('POST', '/api/v1/auth/guest', () =>
      json({ ...guestSession, metadata }),
    );
    renderApp();
    await userEvent.click(
      await screen.findByRole('button', { name: '로그인 없이 둘러보기' }),
    );

    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=all',
    );
    expect(useAuthStore.getState().session?.kind).toBe('guest');
    expect(useAuthStore.getState().member).toBeNull();
  });

  test('비회원 시작에 실패하면 안내하고 머문다', async () => {
    server.on('POST', '/api/v1/auth/guest', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    renderApp();
    await userEvent.click(
      await screen.findByRole('button', { name: '로그인 없이 둘러보기' }),
    );

    expect(
      await screen.findByText(
        '비회원으로 시작하지 못했어요. 다시 시도해 주세요.',
      ),
    ).toBeTruthy();
    expect(screen.queryByTestId('destination')).toBeNull();
  });

  test('회원가입과 소셜 로그인은 각 절차로 연결한다', async () => {
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });

    expect(
      screen
        .getByRole('link', { name: '이메일로 회원가입' })
        .getAttribute('href'),
    ).toBe('/signup');
    expect(
      screen.getByRole('link', { name: '구글 로그인' }).getAttribute('href'),
    ).toBe('/api/v1/auth/social/google/authorize?returnTo=%2F');
    expect(
      screen
        .getByRole('link', { name: '카카오톡 로그인' })
        .getAttribute('href'),
    ).toBe('/api/v1/auth/social/kakao/authorize?returnTo=%2F');
  });
});

describe('세션 쿠키 인증', () => {
  test('보호된 화면은 세션을 확인한 뒤 회원이 아니면 로그인으로 보낸다', async () => {
    const pending = deferred<Response>();
    server.on('GET', '/api/v1/auth/session', () => pending.promise);
    renderApp('/my');

    expect(
      await screen.findByText('로그인 상태를 확인하고 있어요'),
    ).toBeTruthy();
    pending.resolve(json({ ...session(), metadata }));
    expect(
      await screen.findByRole('heading', { name: '이메일로 로그인' }),
    ).toBeTruthy();
  });

  test('세션 확인에 실패하면 로그아웃으로 보지 않고 다시 시도한다', async () => {
    server.on('GET', '/api/v1/auth/session', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    renderApp('/my');
    expect(
      await screen.findByText('로그인 상태를 확인하지 못했어요'),
    ).toBeTruthy();

    server.on('GET', '/api/v1/auth/session', () =>
      json({ ...memberSession(true), metadata }),
    );
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect((await screen.findByTestId('destination')).textContent).toBe('/my');
  });

  test('쓰기 요청에만 세션의 X-CSRF-Token을 붙이고 쿠키를 함께 보낸다', async () => {
    useAuthStore.getState().setSession(memberSession(true));
    server.on('GET', '/api/v1/me/settings', () => json({}));
    server.on('PUT', '/api/v1/me/settings', () => json({}));

    await call('/api/v1/me/settings', 'GET');
    await call('/api/v1/me/settings', 'PUT', { version: 1 });

    const [getCall, putCall] = vi.mocked(fetch).mock.calls;
    const getInit = getCall[1] as RequestInit;
    const putInit = putCall[1] as RequestInit;
    expect(getInit.credentials).toBe('include');
    expect(new Headers(getInit.headers).has('X-CSRF-Token')).toBe(false);
    expect(new Headers(getInit.headers).has('Authorization')).toBe(false);
    expect(new Headers(putInit.headers).get('X-CSRF-Token')).toBe(
      'csrf-member',
    );
  });

  test('회원 API가 401이면 화면의 로그인 상태를 비운다', async () => {
    useAuthStore.getState().setSession(memberSession(true));
    server.on('GET', '/api/v1/me/settings', () =>
      apiError(401, 'AUTHENTICATION_REQUIRED'),
    );

    await expect(call('/api/v1/me/settings', 'GET')).rejects.toMatchObject({
      status: 401,
      code: 'AUTHENTICATION_REQUIRED',
    });
    await waitFor(() => expect(useAuthStore.getState().member).toBeNull());
  });
});
