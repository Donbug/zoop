import { useState } from 'react';
import { act, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import AdminLayout from '@/components/admin/common/AdminLayout';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import { toggleTheme } from '@/util/theme-color';
import { renderRoutes } from '../support/renderRoutes';

vi.mock('@/util/theme-color', () => {
  const toggleTheme = vi.fn();
  return { toggleTheme, useThemeToggle: () => toggleTheme };
});
const session: AdminSession = {
  authenticated: true,
  expired: false,
  expiredReason: null,
  admin: {
    id: 'a',
    email: 'a@zoop.test',
    displayName: '관리자',
    role: 'operator',
  },
  expiresAt: '2099-01-01T00:00:00Z',
  idleExpiresAt: '2099-01-01T00:00:00Z',
  idleTimeoutSeconds: 1800,
  absoluteTimeoutSeconds: 28800,
  csrfToken: 'fixture',
};
beforeEach(() => {
  useAdminSessionStore.getState().setSession(session);
  vi.clearAllMocks();
});
function Content() {
  const [value, setValue] = useState('');
  return (
    <label>
      진행 중 입력
      <input value={value} onChange={(event) => setValue(event.target.value)} />
    </label>
  );
}
test('A-ADM-01~05 본문 건너뛰기와 일반 화면의 테마 전환을 연결해요', async () => {
  const { user } = renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [
          {
            element: <AdminLayout />,
            children: [{ path: '/admin/dashboard', element: <Content /> }],
          },
        ],
      },
    ],
    '/admin/dashboard',
  );
  const skip = screen.getByRole('link', { name: '본문으로 건너뛰기' });
  await user.tab();
  expect(document.activeElement).toBe(skip);
  await user.keyboard('{Enter}');
  expect(document.activeElement).toBe(screen.getByRole('main'));
  await user.click(screen.getByRole('button', { name: '화면 테마 전환' }));
  expect(toggleTheme).toHaveBeenCalledOnce();
});

test('A-ADM-01~05 사이드바는 고정되고 너비를 키보드로 조절해요', async () => {
  window.localStorage.removeItem('zoop:admin-sidebar-width');
  const { user } = renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [
          {
            element: <AdminLayout />,
            children: [{ path: '/admin/dashboard', element: <Content /> }],
          },
        ],
      },
    ],
    '/admin/dashboard',
  );
  const sidebar = screen.getByRole('complementary');
  const resizer = screen.getByRole('separator', { name: '사이드바 너비 조절' });
  expect(sidebar.className).toContain('md:sticky');
  expect(sidebar.className).toContain('md:h-dvh');
  expect(resizer.getAttribute('aria-valuenow')).toBe('224');
  resizer.focus();
  await user.keyboard('{ArrowRight}');
  expect(resizer.getAttribute('aria-valuenow')).toBe('240');
  expect(window.localStorage.getItem('zoop:admin-sidebar-width')).toBe('240');
});

test('A-ADM-01~05 같은 경로에서 관리자가 바뀌면 이전 입력을 제거해요', async () => {
  const { user } = renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [{ path: '/admin/dashboard', element: <Content /> }],
      },
    ],
    '/admin/dashboard',
  );
  await user.type(screen.getByLabelText('진행 중 입력'), '이전 관리자');
  act(() =>
    useAdminSessionStore
      .getState()
      .setSession({ ...session, admin: { ...session.admin!, id: 'b' } }),
  );
  expect(
    (screen.getByLabelText('진행 중 입력') as HTMLInputElement).value,
  ).toBe('');
});
