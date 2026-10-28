import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import { useAuth } from '@/hooks/useAuth';

vi.mock('@/hooks/useAuth');
it.each(['/my', '/onboarding/watchlist'])(
  'allows onboarding but redirects incomplete members from %s',
  (path) => {
    vi.mocked(useAuth).mockReturnValue({
      status: 'ready',
      checking: false,
      failed: false,
      isAuthenticated: true,
      isGuest: false,
      member: { id: 'a', displayName: 'a', email: 'a@test.test' },
      onboardingCompleted: false,
      logout: vi.fn(),
      retry: vi.fn(),
    });
    render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<ProtectedRoute />}>
            <Route path="/my" element={<p>개인 화면</p>} />
            <Route path="/onboarding/*" element={<p>초기 설정</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('초기 설정')).toBeTruthy();
    expect(screen.queryByText('개인 화면')).toBeNull();
  },
);
