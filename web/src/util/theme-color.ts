import { useSyncExternalStore } from 'react';

type Token = 'ink' | 'muted' | 'faint' | 'line' | 'paper' | 'soft' | 'up';
export type ColorTheme = 'light' | 'dark';

const LIGHT: Record<Token, string> = {
  ink: '#1a1a1a',
  muted: '#5f5f5b',
  faint: '#94948f',
  line: '#d6d6d2',
  paper: '#ffffff',
  soft: '#f2f2f0',
  up: '#d23c3c',
};

/** 캔버스에 쓸 zoop 토큰 색. 현재 테마(:root[data-theme])의 값을 읽는다. */
export function themeColor(token: Token) {
  if (typeof document === 'undefined') return LIGHT[token];
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(`--color-zoop-${token}`)
    .trim();
  return value || LIGHT[token];
}

const KEY = 'zoop.theme';

/** 처음 그리기 전에 테마를 정한다. ?theme=dark|light가 있으면 그 값을 쓰고 저장한다. */
export function applyInitialTheme() {
  const query = new URLSearchParams(window.location.search).get('theme');
  const queryTheme = query === 'dark' || query === 'light' ? query : null;
  let theme: string | null = queryTheme;
  try {
    if (queryTheme) localStorage.setItem(KEY, queryTheme);
    else theme = localStorage.getItem(KEY);
  } catch {
    /* 저장소가 없어도 URL로 고른 테마는 적용한다. */
  }
  document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
}

const listeners = new Set<() => void>();

/** 지금 화면 모드(:root[data-theme]) */
export function currentTheme(): ColorTheme {
  if (typeof document === 'undefined') return 'light';
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

function subscribeTheme(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 화면 모드가 바뀌면 다시 그린다. 캔버스(G6)는 이 값이 바뀔 때 토큰 색을 다시 읽는다. */
export function useColorTheme() {
  return useSyncExternalStore<ColorTheme>(
    subscribeTheme,
    currentTheme,
    () => 'light',
  );
}

/** 화면 모드 전환. 새로 불러오지 않아 입력 중인 내용과 화면 상태가 남는다(82번). */
export function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  const url = new URL(window.location.href);
  const hadQuery = url.searchParams.has('theme');
  url.searchParams.delete('theme');
  let stored = true;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    stored = false;
    // 저장소가 없으면 새로 고침 뒤에도 선택이 남도록 URL에 남긴다.
    url.searchParams.set('theme', next);
  }
  // 라우터 상태(history.state)는 그대로 두고 주소의 ?theme=만 맞춘다.
  if (hadQuery || !stored)
    window.history.replaceState(window.history.state, '', url.toString());
  document.documentElement.dataset.theme = next;
  for (const listener of listeners) listener();
}
