// 라이트/다크 테마. <html data-theme="dark">를 켜고 끄며, 선택은 localStorage에 기억한다.
import { useCallback, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const storageKey = "zoop-theme";
const listeners = new Set<() => void>();

function readTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function setTheme(theme: Theme) {
  if (theme === "dark") document.documentElement.dataset.theme = "dark";
  else delete document.documentElement.dataset.theme;
  try {
    localStorage.setItem(storageKey, theme);
  } catch {
    // 저장소를 쓸 수 없는 환경이면 이번 방문 동안만 적용한다.
  }
  for (const listener of listeners) listener();
}

export function useTheme() {
  const theme = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    readTheme,
    () => "light" as Theme,
  );
  const toggle = useCallback(() => setTheme(readTheme() === "dark" ? "light" : "dark"), []);
  return { theme, toggle };
}

/** 화면 폭·동작 줄이기 같은 미디어 쿼리를 구독한다. */
export function useMediaQuery(query: string) {
  return useSyncExternalStore(
    (listener) => {
      const media = window.matchMedia(query);
      media.addEventListener("change", listener);
      return () => media.removeEventListener("change", listener);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
