import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import MapEntryRoute from '@/components/auth/MapEntryRoute';
import { useAuth } from '@/hooks/useAuth';
import OnboardingLayout from '@/components/onboarding/OnboardingLayout';

vi.mock('@/hooks/useAuth');
beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue({
    status: 'ready',
    checking: false,
    failed: false,
    isAuthenticated: false,
    isGuest: false,
    member: null,
    onboardingCompleted: null,
    logout: vi.fn(),
    retry: vi.fn(),
  });
});
function LoginTarget() {
  const location = useLocation();
  return <p>로그인 시작 {location.state?.from?.search}</p>;
}
function open(entry = '/?mode=all&select=node%3AKRX%3A005930') {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/" element={<MapEntryRoute />}>
          <Route index element={<p>시장 지도</p>} />
        </Route>
        <Route path="/login" element={<LoginTarget />} />
        <Route path="/onboarding" element={<p>초기 설정</p>} />
      </Routes>
    </MemoryRouter>,
  );
}
it('redirects an incomplete member to onboarding', () => {
  vi.mocked(useAuth).mockReturnValue({
    ...useAuth(),
    isAuthenticated: true,
    onboardingCompleted: false,
  });
  open('/');
  expect(screen.getByText('초기 설정')).toBeTruthy();
});
it.each(['member', 'guest'])(
  'keeps a confirmed %s session on the map at the service root',
  (kind) => {
    vi.mocked(useAuth).mockReturnValue({
      ...useAuth(),
      isAuthenticated: kind === 'member',
      isGuest: kind === 'guest',
    });
    open('/');
    expect(screen.getByText('시장 지도')).toBeTruthy();
    expect(screen.queryByText(/로그인 시작/)).toBeNull();
  },
);
it('shows login at the service root when there is no session', async () => {
  open('/');
  expect(await screen.findByText(/로그인 시작/)).toBeTruthy();
  expect(screen.queryByText('시장 지도')).toBeNull();
});
it('D-AUT-01 sends a first-time visitor to login and preserves the requested map URL', async () => {
  open();
  expect((await screen.findByText(/로그인 시작/)).textContent).toContain(
    '?mode=all&select=node%3AKRX%3A005930',
  );
  expect(screen.queryByText('시장 지도')).toBeNull();
});
it('waits for the session before displaying the map or redirecting', () => {
  vi.mocked(useAuth).mockReturnValue({
    ...useAuth(),
    status: 'checking',
    checking: true,
  });
  open();
  expect(screen.getByRole('status')).toBeTruthy();
  expect(screen.queryByText('시장 지도')).toBeNull();
  expect(screen.queryByText(/로그인 시작/)).toBeNull();
});
it.each(['member', 'guest'])(
  'allows an established %s session to enter the map',
  (kind) => {
    vi.mocked(useAuth).mockReturnValue({
      ...useAuth(),
      isAuthenticated: kind === 'member',
      isGuest: kind === 'guest',
    });
    open();
    expect(screen.getByText('시장 지도')).toBeTruthy();
  },
);
it('uses the login recovery screen on a failed session check', async () => {
  vi.mocked(useAuth).mockReturnValue({
    ...useAuth(),
    status: 'error',
    failed: true,
  });
  open();
  expect(await screen.findByText(/로그인 시작/)).toBeTruthy();
  expect(screen.queryByText('시장 지도')).toBeNull();
});
it.each([
  ['linked', '소셜 계정을 연결했어요.'],
  ['cancelled', '계정 연결을 취소했어요.'],
  ['failed', '계정을 연결하지 못했어요. 다시 시도해 주세요.'],
])(
  '#381 keeps a social-link result (%s) when an incomplete member is sent to onboarding',
  (result, message) => {
    vi.mocked(useAuth).mockReturnValue({
      ...useAuth(),
      isAuthenticated: true,
      onboardingCompleted: false,
    });
    render(
      <MemoryRouter initialEntries={[`/?social=${result}`]}>
        <Routes>
          <Route path="/" element={<MapEntryRoute />} />
          <Route path="/onboarding" element={<OnboardingLayout />}>
            <Route index element={<p>초기 설정</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('초기 설정')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toBe(message);
  },
);
it('#381 forwards only a known social-link result to onboarding', () => {
  vi.mocked(useAuth).mockReturnValue({
    ...useAuth(),
    isAuthenticated: true,
    onboardingCompleted: false,
  });
  function Where() {
    const location = useLocation();
    return <p>온보딩 {location.search || '(없음)'}</p>;
  }
  render(
    <MemoryRouter initialEntries={['/?social=other&code=abc']}>
      <Routes>
        <Route path="/" element={<MapEntryRoute />} />
        <Route path="/onboarding" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText('온보딩 (없음)')).toBeTruthy();
});
