import { afterEach, beforeEach, expect, it } from 'vitest';
import { applyInitialTheme, themeColor } from '@/util/theme-color';

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

it('reads the current token value for canvas colors and falls back to light', () => {
  expect(themeColor('ink')).toBe('#1a1a1a');
  document.documentElement.style.setProperty('--color-zoop-ink', '#ffffff');
  expect(themeColor('ink')).toBe('#ffffff');
});
