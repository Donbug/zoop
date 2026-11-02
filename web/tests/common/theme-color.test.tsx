import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import {
  applyInitialTheme,
  themeColor,
  toggleTheme,
  useColorTheme,
  useThemeToggle,
} from '@/util/theme-color';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { renderRoutes } from '../support/renderRoutes';

// Dark theme: the first paint follows ?theme= or the saved choice; the canvas reads token values.
beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});
afterEach(() => {
  window.history.replaceState(null, '', '/');
  document.documentElement.style.removeProperty('--color-zoop-ink');
});

it('starts light, follows ?theme=dark and remembers it', () => {
  applyInitialTheme();
  expect(document.documentElement.dataset.theme).toBe('light');
  window.history.replaceState(null, '', '/?theme=dark');
  applyInitialTheme();
  expect(document.documentElement.dataset.theme).toBe('dark');
  window.history.replaceState(null, '', '/');
  applyInitialTheme();
  expect(document.documentElement.dataset.theme).toBe('dark');
});

it('applies the URL theme even when browser storage is unavailable', () => {
  window.history.replaceState(null, '', '/?theme=dark');
  const unavailable = vi
    .spyOn(Storage.prototype, 'setItem')
    .mockImplementation(() => {
      throw new DOMException('blocked');
    });

  applyInitialTheme();

  expect(document.documentElement.dataset.theme).toBe('dark');
  unavailable.mockRestore();
});

it('reads the current token value for canvas colors and falls back to light', () => {
  expect(themeColor('ink')).toBe('#212121');
  document.documentElement.style.setProperty('--color-zoop-ink', '#ffffff');
  expect(themeColor('ink')).toBe('#ffffff');
});

it('82번 toggles without reloading and keeps typed input', () => {
  document.documentElement.dataset.theme = 'light';
  const seen: string[] = [];
  function Probe() {
    const theme = useColorTheme();
    seen.push(theme);
    return <input aria-label="사유" defaultValue="" />;
  }
  render(<Probe />);
  const input = screen.getByRole('textbox', {
    name: '사유',
  }) as HTMLInputElement;
  fireEvent.change(input, { target: { value: '입력 중인 사유' } });

  act(() => {
    toggleTheme();
  });

  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(seen.at(-1)).toBe('dark');
  expect(input.value).toBe('입력 중인 사유');
  expect(localStorage.getItem('zoop.theme')).toBe('dark');
});

function ThemeProbe() {
  const toggle = useThemeToggle();
  const { updateQuery } = useRouteQuery();
  return (
    <>
      <button type="button" onClick={toggle}>
        전환
      </button>
      <button type="button" onClick={() => updateQuery({ node: 'n1' })}>
        노드
      </button>
    </>
  );
}

it.each([false, true])(
  'D-AUT-01 · 82: preserves login return state and hash when updating theme (storage blocked=%s)',
  async (blocked) => {
    document.documentElement.dataset.theme = 'light';
    if (blocked)
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new DOMException('blocked');
      });
    const state = { from: { pathname: '/my', search: '?tab=holdings' } };
    const router = createMemoryRouter(
      [{ path: '/login', element: <ThemeProbe /> }],
      {
        initialEntries: [
          {
            pathname: '/login',
            search: blocked ? '?tab=sign-in' : '?tab=sign-in&theme=light',
            hash: '#email',
            state,
          },
        ],
      },
    );
    render(<RouterProvider router={router} />);
    await userEvent.click(screen.getByRole('button', { name: '전환' }));
    expect(router.state.location.state).toEqual(state);
    expect(router.state.location.hash).toBe('#email');
    expect(new URLSearchParams(router.state.location.search).get('tab')).toBe(
      'sign-in',
    );
    expect(new URLSearchParams(router.state.location.search).get('theme')).toBe(
      blocked ? 'dark' : null,
    );
  },
);

it('82번 drops ?theme through the router so later query updates do not restore it', async () => {
  document.documentElement.dataset.theme = 'light';
  const { user, location } = renderRoutes(
    [{ path: '/', element: <ThemeProbe /> }],
    '/?tab=x&theme=light',
  );

  await user.click(screen.getByRole('button', { name: '전환' }));
  expect(location()).toBe('/?tab=x');
  await user.click(screen.getByRole('button', { name: '노드' }));

  expect(location()).toBe('/?tab=x&node=n1');
  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(localStorage.getItem('zoop.theme')).toBe('dark');
});

it('82번 keeps the choice in the URL when browser storage is unavailable', async () => {
  document.documentElement.dataset.theme = 'light';
  const unavailable = vi
    .spyOn(Storage.prototype, 'setItem')
    .mockImplementation(() => {
      throw new DOMException('blocked');
    });
  const { user, location } = renderRoutes(
    [{ path: '/', element: <ThemeProbe /> }],
    '/',
  );

  await user.click(screen.getByRole('button', { name: '전환' }));
  await user.click(screen.getByRole('button', { name: '노드' }));

  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(location()).toBe('/?theme=dark&node=n1');
  unavailable.mockRestore();
});
