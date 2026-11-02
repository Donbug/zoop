/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  type InitialEntry,
} from 'react-router-dom';
import { afterEach, beforeEach, expect, it } from 'vitest';
import AuthFrame from '@/components/auth/AuthFrame';
import LoginFrame from '@/components/auth/LoginFrame';
import OnboardingLayout from '@/components/onboarding/OnboardingLayout';
import LoginPage from '@/pages/auth/login/LoginPage';
import SignupPage from '@/pages/auth/signup/SignupPage';
import ServiceHeader from '@/components/common/ServiceHeader';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  createFakeServer,
  deferred,
  json,
  apiError,
} from '../support/fakeServer';

let server: ReturnType<typeof createFakeServer>;
const anonymous = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};
const terms = [
  {
    id: 'synthetic-term',
    title: '합성 약관',
    required: true,
    body: '합성 약관 본문',
    bodyAvailable: true,
    version: 'v1',
  },
];
beforeEach(() => {
  document.documentElement.dataset.theme = 'light';
  useAuthStore.getState().clearSession();
  useAuthStore.setState({ status: 'checking' });
  server = createFakeServer();
  server.on('GET', '/api/v1/auth/session', () => json(anonymous));
  server.on('GET', '/api/v1/auth/terms', () =>
    json({ items: terms, nextCursor: null }),
  );
  server.on('GET', '/api/v1/auth/social/providers', () =>
    json({ items: [], nextCursor: null }),
  );
});
afterEach(() => {
  delete document.documentElement.dataset.theme;
});
function Location() {
  const l = useLocation();
  return (
    <output data-testid="location">
      {JSON.stringify({
        path: l.pathname,
        search: l.search,
        hash: l.hash,
        state: l.state,
      })}
    </output>
  );
}
function pages(entry: InitialEntry) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Location />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

it.each(['auth', 'aside', 'login', 'onboarding'] as const)(
  'D-AUT-01/02 D-ONB-01 A1 %s skips to one main without changing the hash',
  async (kind) => {
    const content = <h1>합성 본문</h1>;
    render(
      <MemoryRouter initialEntries={['/screen?keep=1']}>
        <Location />
        {kind === 'auth' ? (
          <AuthFrame screen="D-AUT-02">{content}</AuthFrame>
        ) : kind === 'aside' ? (
          <AuthFrame screen="D-AUT-02" aside={<p>합성 설명</p>}>
            {content}
          </AuthFrame>
        ) : kind === 'login' ? (
          <LoginFrame>{content}</LoginFrame>
        ) : (
          <Routes>
            <Route element={<OnboardingLayout />}>
              <Route path="/screen" element={content} />
            </Route>
          </Routes>
        )}
      </MemoryRouter>,
    );
    const before = screen.getByTestId('location').textContent;
    await userEvent.click(
      screen.getByRole('link', { name: '본문으로 건너뛰기' }),
    );
    expect(document.activeElement).toBe(screen.getByRole('main'));
    expect(document.querySelectorAll('#service-main')).toHaveLength(1);
    expect(screen.getByTestId('location').textContent).toBe(before);
  },
);

it('D-AUT-01/02 A4 keeps from across both auth links without introducing an email', async () => {
  const state = {
    from: {
      pathname: '/companies/KRX:005930',
      search: '?tab=documents',
      hash: '#context',
    },
  };
  pages({ pathname: '/login', state });
  await userEvent.click(
    await screen.findByRole('link', { name: '이메일로 회원가입' }),
  );
  expect(JSON.parse(screen.getByTestId('location').textContent!).state).toEqual(
    state,
  );
  await userEvent.click(
    await screen.findByRole('link', { name: '← 시작 화면으로' }),
  );
  expect(JSON.parse(screen.getByTestId('location').textContent!).state).toEqual(
    state,
  );
  expect(
    ((await screen.findByLabelText('이메일')) as HTMLInputElement).value,
  ).toBe('');
});

it('D-AUT-02 A3 EMAIL_TAKEN offers login with destination and no email prefill', async () => {
  server.on('POST', '/api/v1/auth/signup', () => apiError(409, 'EMAIL_TAKEN'));
  const state = { from: { pathname: '/my', search: '?keep=1' } };
  pages({ pathname: '/signup', state });
  const user = userEvent.setup();
  await user.type(
    await screen.findByLabelText('이메일'),
    'synthetic@example.invalid',
  );
  await user.type(screen.getByLabelText('비밀번호'), 'Synthetic-only-123!');
  await user.click(await screen.findByLabelText('모두 동의'));
  expect(
    screen.queryByRole('link', { name: '이 이메일로 로그인하기' }),
  ).toBeNull();
  await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
  await user.click(
    await screen.findByRole('link', { name: '이 이메일로 로그인하기' }),
  );
  expect(JSON.parse(screen.getByTestId('location').textContent!)).toMatchObject(
    { path: '/login', search: '', state },
  );
  expect(
    ((await screen.findByLabelText('이메일')) as HTMLInputElement).value,
  ).toBe('');
});

it('D-AUT-01 A2 discards a provider response after leaving login', async () => {
  const response = deferred<Response>();
  server.on('GET', '/api/v1/auth/social/providers', () => response.promise);
  pages('/login');
  await userEvent.click(
    await screen.findByRole('link', { name: '이메일로 회원가입' }),
  );
  await screen.findByRole('heading', { name: '이메일로 가입하기' });
  await act(async () =>
    response.resolve(
      json({ items: [{ id: 'google', name: 'Google' }], nextCursor: null }),
    ),
  );
  expect(screen.queryByRole('link', { name: '구글 로그인' })).toBeNull();
});

it.each(['light', 'dark'] as const)(
  'D-GRP-01 G1/G2 %s theme action changes icon and name in place',
  async (theme) => {
    document.documentElement.dataset.theme = theme;
    render(
      <MemoryRouter>
        <ServiceHeader />
        <input aria-label="입력 유지" defaultValue="합성 입력" />
      </MemoryRouter>,
    );
    const label =
      theme === 'light' ? '다크 모드로 바꾸기' : '라이트 모드로 바꾸기';
    const button = screen.getByRole('button', { name: label });
    expect(
      theme === 'light'
        ? button.querySelector('img')?.getAttribute('src')
        : button.querySelector('svg circle'),
    ).toBeTruthy();
    button.focus();
    await userEvent.keyboard('{Enter}');
    expect(
      screen.getByRole('button', {
        name: theme === 'light' ? '라이트 모드로 바꾸기' : '다크 모드로 바꾸기',
      }),
    ).toBe(button);
    expect((screen.getByLabelText('입력 유지') as HTMLInputElement).value).toBe(
      '합성 입력',
    );
    const css = readFileSync('src/components/common/service-shell.css', 'utf8');
    expect(css).not.toMatch(
      /\.relationship-user-tools\s*>\s*button\s*\{\s*display:\s*none/,
    );
  },
);
