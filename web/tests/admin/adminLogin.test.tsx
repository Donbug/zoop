import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { useLocation } from 'react-router-dom';
import AdminLoginPage from '@/pages/admin/login/AdminLoginPage';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import AdminLayout from '@/components/admin/common/AdminLayout';
import { adminCall } from '@/apis/admin/auth';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import { useAuthStore } from '@/stores/useAuthStore';
import type { AdminSession } from '@/types/admin';
import type { Session } from '@/types/auth';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  noContent,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const SESSION = '/api/v1/admin/auth/session';
const LOGIN = '/api/v1/admin/auth/login';
const LOGOUT = '/api/v1/admin/auth/logout';

function adminSession(overrides: Partial<AdminSession> = {}): AdminSession {
  return {
    authenticated: false,
    expired: false,
    expiredReason: null,
    admin: null,
    expiresAt: null,
    idleExpiresAt: null,
    idleTimeoutSeconds: 1800,
    absoluteTimeoutSeconds: 28800,
    csrfToken: null,
    ...overrides,
  };
}

const signedIn = () =>
  adminSession({
    authenticated: true,
    admin: {
      id: 'adm-1',
      email: 'admin@zoop.test',
      displayName: '운영 관리자',
      role: 'operator',
    },
    expiresAt: '2099-01-01T08:00:00Z',
    idleExpiresAt: '2099-01-01T00:30:00Z',
    csrfToken: 'csrf-admin',
  });

const memberSession: Session = {
  authenticated: true,
  kind: 'member',
  user: { id: 'mem-1', email: 'member@zoop.test', displayName: '회원' },
  setup: { completed: true, tutorialCompleted: true },
  csrfToken: 'csrf-member',
  expiresAt: null,
};

function Destination() {
  const location = useLocation();
  return <output data-testid="destination">{location.pathname}</output>;
}

function openAdmin(path: string) {
  return renderRoutes(
    [
      { path: '/admin/login', element: <AdminLoginPage /> },
      {
        element: <AdminProtectedRoute />,
        children: [
          {
            element: <AdminLayout />,
            children: [
              { path: '/admin', element: <Destination /> },
              { path: '/admin/stats', element: <Destination /> },
              { path: '/admin/members', element: <Destination /> },
            ],
          },
        ],
      },
      { path: '/login', element: <p>회원 로그인 화면</p> },
    ],
    path,
  );
}

async function submit(
  user: ReturnType<typeof openAdmin>['user'],
  email: string,
  password: string,
) {
  if (email) await user.type(screen.getByLabelText('관리자 이메일'), email);
  if (password) await user.type(screen.getByLabelText('비밀번호'), password);
  await user.click(screen.getByRole('button', { name: '관리자 로그인' }));
}

let server: FakeServer;

beforeEach(() => {
  useAdminSessionStore.setState({
    status: 'checking',
    session: null,
    admin: null,
    revision: 0,
  });
  useAuthStore.getState().clearSession();
  server = createFakeServer();
  server.on('GET', SESSION, () => json(adminSession()));
});

describe('A-ADM-05c 관리자 로그인 (FS073)', () => {
  test('와이어프레임대로 제목·입력·버튼·세션 안내를 보여 준다', async () => {
    openAdmin('/admin/login');

    expect(
      await screen.findByRole('heading', { name: '줍 관리자' }),
    ).toBeTruthy();
    expect(screen.getByLabelText('관리자 이메일')).toBeTruthy();
    expect(screen.getByLabelText('비밀번호')).toBeTruthy();
    expect(
      await screen.findByText(
        '관리자 세션은 회원 세션과 분리돼요 · 30분 동안 활동이 없으면 만료',
      ),
    ).toBeTruthy();
  });

  test('빈 입력은 요청하지 않고 안내한다', async () => {
    const { user } = openAdmin('/admin/login');
    await screen.findByRole('heading', { name: '줍 관리자' });
    await submit(user, 'admin@zoop.test', '');

    expect(
      screen.getByText('관리자 이메일과 비밀번호를 모두 입력해 주세요.'),
    ).toBeTruthy();
    expect(server.calls('POST', LOGIN)).toHaveLength(0);
  });

  test('로그인에 성공하면 운영 대시보드로 가고 관리자 정보를 보여 준다', async () => {
    server.on('POST', LOGIN, () => json(signedIn()));
    const { user } = openAdmin('/admin/login');
    await screen.findByRole('heading', { name: '줍 관리자' });
    await submit(user, ' admin@zoop.test ', 'secret-pass');

    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/admin',
    );
    expect(server.calls('POST', LOGIN)[0].body).toEqual({
      email: 'admin@zoop.test',
      password: 'secret-pass',
    });
    expect(screen.getByText('운영 관리자')).toBeTruthy();
  });

  test('회원 로그인 중에도 관리자 로그인에 회원 CSRF를 보내지 않는다', async () => {
    useAuthStore.getState().setSession(memberSession);
    server.on('POST', LOGIN, () => json(signedIn()));
    const { user } = openAdmin('/admin/login');
    await screen.findByRole('heading', { name: '줍 관리자' });
    await submit(user, 'admin@zoop.test', 'secret-pass');
    await screen.findByTestId('destination');

    const [, init] = vi
      .mocked(fetch)
      .mock.calls.find(([url]) => String(url).endsWith(LOGIN))!;
    expect(new Headers(init?.headers).get('X-CSRF-Token')).toBeNull();
    expect(useAuthStore.getState().member?.id).toBe('mem-1');
  });

  test('보호된 관리자 화면에서 왔으면 로그인 후 그 화면으로 돌아간다', async () => {
    server.on('POST', LOGIN, () => json(signedIn()));
    const { user } = openAdmin('/admin/members');

    await screen.findByRole('heading', { name: '줍 관리자' });
    await submit(user, 'admin@zoop.test', 'secret-pass');
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/admin/members',
    );
  });

  test('인증 실패와 권한 없음을 구분해 안내하고 입력을 유지한다', async () => {
    server.on('POST', LOGIN, () => apiError(401, 'INVALID_CREDENTIALS'));
    const { user } = openAdmin('/admin/login');
    await screen.findByRole('heading', { name: '줍 관리자' });
    await submit(user, 'admin@zoop.test', 'wrong-pass');

    expect(
      await screen.findByText('관리자 이메일 또는 비밀번호가 맞지 않아요.'),
    ).toBeTruthy();
    expect(
      (screen.getByLabelText('관리자 이메일') as HTMLInputElement).value,
    ).toBe('admin@zoop.test');

    server.on('POST', LOGIN, () => apiError(403, 'ACCESS_DENIED'));
    await user.click(screen.getByRole('button', { name: '관리자 로그인' }));
    expect(
      await screen.findByText(
        '관리자 권한이 없는 계정이에요. 권한을 확인해 주세요.',
      ),
    ).toBeTruthy();
    expect(screen.queryByTestId('destination')).toBeNull();
  });

  test('이미 관리자 세션이 있으면 로그인 화면을 건너뛴다', async () => {
    server.on('GET', SESSION, () => json(signedIn()));
    openAdmin('/admin/login');

    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/admin',
    );
  });
});

describe('A-ADM-01 관리자 공통 메뉴', () => {
  test('현재 메뉴를 표시하고 사이드바를 숨겼다가 다시 연다', async () => {
    server.on('GET', SESSION, () => json(signedIn()));
    const { user } = openAdmin('/admin');

    await screen.findByTestId('destination');
    expect(
      screen
        .getByRole('link', { name: '대시보드' })
        .getAttribute('aria-current'),
    ).toBe('page');

    await user.click(screen.getByRole('link', { name: '이용 통계' }));
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/admin/stats',
    );
    expect(
      screen
        .getByRole('link', { name: '이용 통계' })
        .getAttribute('aria-current'),
    ).toBe('page');

    await user.click(screen.getByRole('button', { name: '메뉴 숨기기' }));
    expect(
      screen.queryByRole('navigation', { name: '관리자 메뉴' }),
    ).toBeNull();
    await user.click(screen.getByRole('button', { name: '메뉴 열기' }));
    expect(
      screen
        .getByRole('link', { name: '이용 통계' })
        .getAttribute('aria-current'),
    ).toBe('page');
  });
});

describe('A-ADM-05c 관리자 접근 제어 (FS073·NFS001)', () => {
  test('관리자 세션이 없으면 관리자 화면 대신 로그인으로 보낸다', async () => {
    const pending = deferred<Response>();
    server.on('GET', SESSION, () => pending.promise);
    openAdmin('/admin');

    expect(
      await screen.findByText('관리자 세션을 확인하고 있어요'),
    ).toBeTruthy();
    pending.resolve(json(adminSession()));
    expect(
      await screen.findByRole('heading', { name: '줍 관리자' }),
    ).toBeTruthy();
  });

  test('회원으로 로그인해 있어도 관리자 화면에 들어갈 수 없다', async () => {
    useAuthStore.getState().setSession(memberSession);
    openAdmin('/admin');

    expect(
      await screen.findByRole('heading', { name: '줍 관리자' }),
    ).toBeTruthy();
    expect(screen.queryByTestId('destination')).toBeNull();
  });

  test('세션이 만료됐으면 사유를 안내한다', async () => {
    server.on('GET', SESSION, () =>
      json(adminSession({ expired: true, expiredReason: 'idle' })),
    );
    openAdmin('/admin');

    expect(
      await screen.findByText(
        '오래 활동이 없어 관리자 세션이 만료됐어요. 다시 로그인해 주세요.',
      ),
    ).toBeTruthy();
  });

  test('세션 확인에 실패하면 로그아웃으로 보지 않고 다시 시도한다', async () => {
    server.on('GET', SESSION, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = openAdmin('/admin');

    expect(
      await screen.findByText('관리자 세션을 확인하지 못했어요.'),
    ).toBeTruthy();
    server.on('GET', SESSION, () => json(signedIn()));
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/admin',
    );
  });

  test('관리자 로그아웃은 관리자 CSRF로 세션만 폐기하고 회원 세션은 남긴다', async () => {
    useAuthStore.getState().setSession(memberSession);
    server.on('GET', SESSION, () => json(signedIn()));
    server.on('POST', LOGOUT, () => noContent());
    const { user } = openAdmin('/admin');

    await screen.findByTestId('destination');
    await user.click(screen.getByRole('button', { name: '관리자 로그아웃' }));

    expect(
      await screen.findByRole('heading', { name: '줍 관리자' }),
    ).toBeTruthy();
    const [, init] = vi
      .mocked(fetch)
      .mock.calls.find(([url]) => String(url).endsWith(LOGOUT))!;
    expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('csrf-admin');
    expect(useAdminSessionStore.getState().admin).toBeNull();
    expect(useAuthStore.getState().member?.id).toBe('mem-1');
  });

  test('관리자 API의 401은 관리자 세션만 비운다', async () => {
    useAuthStore.getState().setSession(memberSession);
    useAdminSessionStore.getState().setSession(signedIn());
    server.on('GET', '/api/v1/admin/dashboard', () =>
      apiError(401, 'AUTH_REQUIRED'),
    );

    await expect(
      adminCall('/api/v1/admin/dashboard', 'GET'),
    ).rejects.toMatchObject({ status: 401 });
    await waitFor(() =>
      expect(useAdminSessionStore.getState().admin).toBeNull(),
    );
    expect(useAuthStore.getState().member?.id).toBe('mem-1');
  });
});
