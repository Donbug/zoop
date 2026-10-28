import { useSyncExternalStore } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

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

/**
 * 화면 모드 전환. 새로 불러오지 않아 입력 중인 내용과 화면 상태가 남는다(82번).
 * 주소의 ?theme=은 건드리지 않는다. 라우터 안에서는 useThemeToggle로 주소까지 맞춘다.
 */
export function toggleTheme(): { theme: ColorTheme; stored: boolean } {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  let stored = true;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    stored = false;
  }
  document.documentElement.dataset.theme = next;
  for (const listener of listeners) listener();
  return { theme: next, stored };
}

/**
 * 화면 모드를 바꾸고 주소의 ?theme=을 라우터로 맞춘다.
 * 저장했으면 ?theme=을 지워 저장한 값이 다음 새로 고침에 쓰이게 하고, 저장소가 없으면 주소에 남긴다.
 * 라우터를 거쳐야 이후 주소 갱신(useRouteQuery)이 예전 ?theme=을 되살리지 않는다.
 */
export function useThemeToggle() {
  const location = useLocation();
  const navigate = useNavigate();
  return () => {
    const { theme, stored } = toggleTheme();
    const wanted = stored ? null : theme;
    const next = new URLSearchParams(location.search);
    if (next.get('theme') === wanted) return;
    if (wanted) next.set('theme', wanted);
    else next.delete('theme');
    navigate(
      {
        pathname: location.pathname,
        search: next.size ? `?${next}` : '',
        hash: location.hash,
      },
      { replace: true, preventScrollReset: true, state: location.state },
    );
  };
}
