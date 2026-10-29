import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { expect, it } from 'vitest';
import RouteError from '@/components/common/RouteError';

it('shows a not found page and a map link for an unknown route', () => {
  const router = createMemoryRouter(
    [{ path: '*', element: <RouteError notFound /> }],
    { initialEntries: ['/unknown'] },
  );
  render(<RouterProvider router={router} />);
  expect(
    screen.getByRole('heading', { name: '페이지를 찾을 수 없어요' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('link', { name: '지도로 돌아가기' }).getAttribute('href'),
  ).toBe('/');
});

it('FS001 F5 gives the 404 return link a mobile touch target', () => {
  const router = createMemoryRouter(
    [{ path: '*', element: <RouteError notFound /> }],
    { initialEntries: ['/unknown'] },
  );
  render(<RouterProvider router={router} />);
  const link = screen.getByRole('link', { name: '지도로 돌아가기' });
  expect(link.classList.contains('max-md:min-h-10')).toBe(true);
  expect(link.classList.contains('max-md:min-w-10')).toBe(true);
});
