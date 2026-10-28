import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import {
  applyInitialTheme,
  themeColor,
  toggleTheme,
  useColorTheme,
} from '@/util/theme-color';

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
  expect(themeColor('ink')).toBe('#1a1a1a');
  document.documentElement.style.setProperty('--color-zoop-ink', '#ffffff');
  expect(themeColor('ink')).toBe('#ffffff');
});

it('82번 toggles without reloading, keeps typed input and router state, and drops ?theme', () => {
  document.documentElement.dataset.theme = 'light';
  window.history.replaceState(
    { idx: 3, key: 'k' },
    '',
    '/admin?tab=x&theme=light',
  );
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

  act(() => toggleTheme());

  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(seen.at(-1)).toBe('dark');
  expect(input.value).toBe('입력 중인 사유');
  expect(localStorage.getItem('zoop.theme')).toBe('dark');
  expect(window.location.search).toBe('?tab=x');
  expect(window.history.state).toEqual({ idx: 3, key: 'k' });
});

it('82번 keeps the choice in the URL when browser storage is unavailable', () => {
  document.documentElement.dataset.theme = 'light';
  const unavailable = vi
    .spyOn(Storage.prototype, 'setItem')
    .mockImplementation(() => {
      throw new DOMException('blocked');
    });

  toggleTheme();

  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(new URLSearchParams(window.location.search).get('theme')).toBe('dark');
  unavailable.mockRestore();
});
