import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import SignupPage from '@/pages/auth/signup/SignupPage';
import LoginPage from '@/pages/auth/login/LoginPage';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiError, createFakeServer, json } from '../support/fakeServer';
import type { MemberSession } from '@/types/auth/session';

// 모든 계정·쿠키 값은 합성이다. 소셜 신규 인증은 서버의 zoop_oauth_pending 쿠키에만 있다.
const anonymous: MemberSession = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};
const socialMember: MemberSession = {
  authenticated: true,
  kind: 'member',
  user: {
    id: 'synthetic-social-member',
    email: 'social@example.test',
    displayName: '소셜 회원',
  },
  setup: { completed: false, tutorialCompleted: false },
  csrfToken: 'synthetic-csrf',
  expiresAt: '2099-01-01T00:00:00Z',
};
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

function open(path = '/signup?social=pending') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/onboarding" element={<Destination />} />
        </Route>
        <Route path="/" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
  return userEvent.setup();
}

describe('D-AUT-02 소셜 가입 완료 (/signup?social=pending)', () => {
  it('이메일·비밀번호 없이 표시 이름과 약관 동의만 보내고, 가입 후 초기 설정으로 간다', async () => {
    server.on('POST', '/api/v1/auth/social/signup', () => {
      current = socialMember;
      return json(socialMember, 201);
    });
    const user = open();

    expect(
      await screen.findByRole('heading', { name: '소셜 계정으로 가입하기' }),
    ).toBeTruthy();
    expect(screen.queryByLabelText('이메일')).toBeNull();
    expect(screen.queryByLabelText('비밀번호')).toBeNull();

    await screen.findByLabelText('모두 동의');
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect(await screen.findByText('필수 약관에 동의해 주세요.')).toBeTruthy();
    expect(server.calls('POST', '/api/v1/auth/social/signup')).toHaveLength(0);

    await user.type(screen.getByLabelText('표시 이름 (선택)'), ' 소셜 회원 ');
    await user.click(screen.getByLabelText('모두 동의'));
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));

    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/onboarding',
    );
    expect(server.calls('POST', '/api/v1/auth/social/signup')[0].body).toEqual({
      displayName: '소셜 회원',
      agreements: [
        { id: 'service', version: 'v1', accepted: true },
        { id: 'privacy', version: 'v2', accepted: true },
      ],
    });
    expect(server.calls('POST', '/api/v1/auth/signup')).toHaveLength(0);
  });

  it('소셜 인증이 만료됐으면(403) 다시 소셜 로그인하도록 안내한다', async () => {
    server.on('POST', '/api/v1/auth/social/signup', () =>
      apiError(403, 'ACCESS_DENIED'),
    );
    const user = open();
    await screen.findByLabelText('모두 동의');
    await user.click(screen.getByLabelText('모두 동의'));
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));

    expect(
      await screen.findByText(
        '소셜 인증이 만료됐거나 확인되지 않았어요. 로그인 화면에서 소셜 로그인을 다시 시작해 주세요.',
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole('link', { name: '로그인 화면으로' })
        .getAttribute('href'),
    ).toBe('/login');
  });

  it('같은 이메일 계정이 이미 있으면(409) 이메일 로그인 후 연결하도록 안내한다', async () => {
    server.on('POST', '/api/v1/auth/social/signup', () =>
      apiError(409, 'SOCIAL_LINK_REQUIRED'),
    );
    const user = open();
    await screen.findByLabelText('모두 동의');
    await user.click(screen.getByLabelText('모두 동의'));
    await user.click(screen.getByRole('button', { name: '가입하고 시작하기' }));

    expect(
      await screen.findByText(
        '이미 같은 이메일로 가입한 계정이 있어요. 이메일로 로그인한 뒤 소셜 계정을 연결해 주세요.',
      ),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: '로그인 화면으로' })).toBeTruthy();
  });

  it('social 표시가 없으면 기존 이메일 가입 화면이다', async () => {
    open('/signup');
    expect(
      await screen.findByRole('heading', { name: '이메일로 가입하기' }),
    ).toBeTruthy();
    await waitFor(() => expect(screen.getByLabelText('이메일')).toBeTruthy());
  });
});
