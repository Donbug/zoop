import { render, screen } from '@testing-library/react';
import { isValidElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { router } from '@/App';
import AppLayout from '@/components/common/AppLayout';
import ProtectedRoute from '@/components/common/ProtectedRoute';

describe('PR #23 route and shared layout regression', () => {
  it('keeps the graph route separate from the existing application layout', () => {
    expect(router.routes.some((route) => route.path === '/')).toBe(true);

    const layoutRoute = router.routes.find(
      (route) =>
        isValidElement(route.element) && route.element.type === AppLayout,
    );
    expect(layoutRoute).toBeDefined();
    expect(layoutRoute?.children?.map((route) => route.path)).toEqual(
      expect.arrayContaining(['/stocks', '/companies/:id', '/briefing']),
    );

    const protectedRoute = layoutRoute?.children?.find(
      (route) =>
        isValidElement(route.element) && route.element.type === ProtectedRoute,
    );
    expect(protectedRoute?.children?.map((route) => route.path)).toContain(
      '/my',
    );
  });

  it('preserves the existing desktop header and mobile bottom navigation', () => {
    render(
      <MemoryRouter>
        <AppLayout />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('데스크톱 주 메뉴')).toBeTruthy();
    expect(screen.getByLabelText('모바일 주 메뉴')).toBeTruthy();
  });
});
