import { useLayoutEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

/** D-COM-01 D8: 같은 이력의 위치만 복원하고, 비동기 본문 높이를 기다린다. */
export function useCompanyScroll(scope: string, ready: boolean) {
  const location = useLocation();
  const restore = useRef<(() => void) | null>(null);
  const settled = useRef(ready);
  const previousPage = useRef<{ pathname: string; scope: string } | null>(null);
  const pathname = location.pathname;
  const url = location.pathname + location.search;
  useLayoutEffect(() => {
    const changedPage =
      previousPage.current?.pathname !== pathname ||
      previousPage.current?.scope !== scope;
    previousPage.current = { pathname, scope };
    const key = `zoop.company.scroll:${scope}:${location.key}`;
    let savedY: number | null = null;
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) ?? 'null');
      if (saved?.url === url && Number.isFinite(saved.y) && saved.y >= 0)
        savedY = saved.y;
    } catch {
      /* optional history persistence */
    }
    const target = savedY ?? 0;
    let pending = savedY !== null;
    let y = pending ? target : window.scrollY;
    let frame = 0;
    const observer =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => attempt());
    function attempt() {
      if (!pending || !settled.current) return;
      const height = Math.max(
        document.documentElement.scrollHeight,
        document.body.scrollHeight,
      );
      if (observer && height - window.innerHeight < target) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!settled.current) return;
        window.scrollTo({ top: target, behavior: 'instant' });
        pending = false;
        y = target;
        observer?.disconnect();
      });
    }
    const onScroll = () => {
      if (!pending) y = window.scrollY;
    };
    const cancelRestore = () => {
      pending = false;
      y = window.scrollY;
      cancelAnimationFrame(frame);
      observer?.disconnect();
    };
    // D8: query pushes/replacements keep the current viewport. Only entering
    // another company/member page starts at the top without saved history.
    if (!pending && changedPage) {
      window.scrollTo(0, 0);
      y = 0;
    } else if (pending) observer?.observe(document.body);
    restore.current = attempt;
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('wheel', cancelRestore, { passive: true });
    window.addEventListener('touchstart', cancelRestore, { passive: true });
    attempt();
    return () => {
      restore.current = null;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('wheel', cancelRestore);
      window.removeEventListener('touchstart', cancelRestore);
      try {
        sessionStorage.setItem(key, JSON.stringify({ url, y }));
      } catch {
        /* storage can be blocked */
      }
    };
  }, [location.key, pathname, scope, url]);
  useLayoutEffect(() => {
    settled.current = ready;
    restore.current?.();
  }, [ready]);
}
