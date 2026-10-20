type Token = 'ink' | 'muted' | 'faint' | 'line' | 'paper' | 'soft' | 'up';

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

/** 화면 모드 전환. 캔버스 색을 다시 읽도록 새로 불러온다. */
export function toggleTheme() {
  const next =
    document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  const url = new URL(window.location.href);
  url.searchParams.delete('theme');
  try {
    localStorage.setItem(KEY, next);
  } catch {
    // 캔버스를 다시 그리려고 새로 불러와도 선택이 사라지지 않게 URL에 남긴다.
    url.searchParams.set('theme', next);
  }
  document.documentElement.dataset.theme = next;
  window.location.replace(url.toString());
}
