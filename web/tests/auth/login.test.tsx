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

let currentSession: Session;
function memberSession(completed: boolean): Session {
  currentSession = session({
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
  return currentSession;
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
  currentSession = session();
  server = createFakeServer();
  server.on('GET', '/api/v1/me/settings', () => json({ watchlistIds: [] }));
  server.on('GET', '/api/v1/portfolio', () =>
    json({ holdings: [{ companyId: 'synthetic-company' }] }),
  );
  server.on('GET', '/api/v1/auth/session', () =>
    json({ ...currentSession, metadata }),
  );
});

describe('D-AUT-01 이메일 로그인 (FS002·FS006)', () => {
  test('로그인은 됐지만 종목을 확인하지 못하면(설정 API 404) 이동할 화면을 추측하지 않고 다시 확인만 제공한다', async () => {
    server.on('POST', '/api/v1/auth/login', () =>
      json({ ...memberSession(true), metadata }),
    );
    server.on('GET', '/api/v1/me/settings', () =>
      apiError(404, 'RESOURCE_NOT_FOUND'),
    );
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await fillAndSubmit('member@zoop.test', 'secret-pass');

    expect(
      await screen.findByText(
        '계정 상태와 이동할 화면을 확인하지 못했어요. 다시 확인해 주세요.',
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole('button', { name: '로그인 상태 다시 확인' }),
    ).toBeTruthy();
    expect(screen.queryByTestId('destination')).toBeNull();
  });

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

  test('초기 설정을 마친 회원은 시장 전체 지도로 간다', async () => {
    server.on('POST', '/api/v1/auth/login', () =>
      json({ ...memberSession(true), metadata }),
    );
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await fillAndSubmit('member@zoop.test', 'secret-pass');

    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=all',
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
      '/?mode=all',
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
      '/?mode=all',
    );
  });
});

describe('D-AUT-01 시작 방법 선택 (FS001·FS005)', () => {
  test('로그인 없이 둘러보면 비회원 세션을 시작하고 시장 전체 지도로 간다', async () => {
    server.on('POST', '/api/v1/auth/guest', () => {
      currentSession = guestSession;
      return json({ ...currentSession, metadata });
    });
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

  test('회원가입과 서버에 설정된 소셜 로그인만 각 절차로 연결한다', async () => {
    server.on('GET', '/api/v1/auth/social/providers', (request) =>
      request.query.get('cursor') === 'providers-2'
        ? json({ items: [{ id: 'kakao', name: 'Kakao' }], nextCursor: null })
        : json({
            items: [{ id: 'google', name: 'Google' }],
            nextCursor: 'providers-2',
          }),
    );
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });

    expect(
      screen
        .getByRole('link', { name: '이메일로 회원가입' })
        .getAttribute('href'),
    ).toBe('/signup');
    // 서버는 허용 경로(/login·/signup·/)로만 돌려보내므로 로그인 화면으로 돌아와 FS006 분기를 잇는다.
    expect(
      (await screen.findByRole('link', { name: '구글 로그인' })).getAttribute(
        'href',
      ),
    ).toBe('/api/v1/auth/social/google/authorize?returnTo=%2Flogin');
    expect(
      (
        await screen.findByRole('link', { name: '카카오톡 로그인' })
      ).getAttribute('href'),
    ).toBe('/api/v1/auth/social/kakao/authorize?returnTo=%2Flogin');
    expect(server.calls('GET', '/api/v1/auth/social/providers')).toHaveLength(
      2,
    );
  });

  test('소셜 제공자 목록을 불러오지 못하면 소셜 버튼을 두지 않는다', async () => {
    server.on('GET', '/api/v1/auth/social/providers', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    renderApp();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await waitFor(() =>
      expect(server.calls('GET', '/api/v1/auth/social/providers')).toHaveLength(
        1,
      ),
    );
    expect(screen.queryByRole('link', { name: '구글 로그인' })).toBeNull();
    expect(screen.queryByRole('link', { name: '카카오톡 로그인' })).toBeNull();
  });

  test.each([
    ['cancelled', '소셜 로그인을 취소했어요.'],
    ['failed', '소셜 로그인을 완료하지 못했어요. 잠시 후 다시 시도해 주세요.'],
    ['email_required', /확인된 이메일을 받지 못했어요/],
    ['link_required', /이미 이메일로 가입한 계정이에요/],
  ])('소셜 인증 결과(%s)를 안내한다', async (result, message) => {
    renderApp(`/login?social=${result}`);
    expect(await screen.findByText(message)).toBeTruthy();
  });
});

describe('세션 쿠키 인증', () => {
  test('보호된 화면은 세션을 확인한 뒤 회원이 아니면 로그인으로 보낸다', async () => {
    const pending = deferred<Response>();
    server.on('GET', '/api/v1/auth/session', () => pending.promise);
    renderApp('/my');

    expect(
      await screen.findByText('로그인 상태를 확인하고 있어요.'),
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
      await screen.findByText('로그인 상태를 확인하지 못했어요.'),
    ).toBeTruthy();

    server.on('GET', '/api/v1/auth/session', () =>
      json({ ...memberSession(true), metadata }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '세션 다시 확인' }),
    );
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

  test('세션 확인에 실패해도 로그인 폼을 보여 주고 로그인할 수 있다', async () => {
    let loggedIn = false;
    server.on('GET', '/api/v1/auth/session', () =>
      loggedIn
        ? json({ ...memberSession(false), metadata })
        : apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    server.on('POST', '/api/v1/auth/login', () => {
      loggedIn = true;
      return json({ ...memberSession(false), metadata });
    });
    renderApp();

    expect(
      await screen.findByText('로그인 상태를 확인하지 못했어요.'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: '세션 다시 확인' })).toBeTruthy();
    await screen.findByRole('heading', { name: '이메일로 로그인' });
    await fillAndSubmit('member@zoop.test', 'secret-pass');

    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/onboarding',
    );
  });
});
