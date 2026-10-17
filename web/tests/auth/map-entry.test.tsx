import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import MapEntryRoute from '@/components/auth/MapEntryRoute';
import { useAuth } from '@/hooks/useAuth';

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
function open() {
  render(
    <MemoryRouter initialEntries={['/?mode=all&select=node%3AKRX%3A005930']}>
      <Routes>
        <Route path="/" element={<MapEntryRoute />}>
          <Route index element={<p>시장 지도</p>} />
        </Route>
        <Route path="/login" element={<LoginTarget />} />
      </Routes>
    </MemoryRouter>,
  );
}
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
