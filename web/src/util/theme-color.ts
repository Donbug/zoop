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
  let theme: string | null = null;
  try {
    const query = new URLSearchParams(window.location.search).get('theme');
    if (query === 'dark' || query === 'light') localStorage.setItem(KEY, query);
    theme = localStorage.getItem(KEY);
  } catch {
    /* 저장소가 없어도 라이트로 연다. */
  }
  document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
}

/** 화면 모드 전환. 캔버스 색을 다시 읽도록 새로 불러온다. */
export function toggleTheme() {
  const next =
    document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* 저장하지 못해도 이번 화면에는 적용한다. */
  }
  const url = new URL(window.location.href);
  url.searchParams.delete('theme');
  document.documentElement.dataset.theme = next;
  window.location.replace(url.toString());
}
