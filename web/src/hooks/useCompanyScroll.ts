import { useLayoutEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

/** D-COM-01 D8: 같은 이력의 위치만 복원하고, 비동기 본문 높이를 기다린다. */
export function useCompanyScroll(scope: string, ready: boolean) {
  const location = useLocation();
  const restore = useRef<(() => void) | null>(null);
  const settled = useRef(ready);
  const url = location.pathname + location.search;
  useLayoutEffect(() => {
    const key = `zoop.company.scroll:${scope}:${location.key}`;
    let target = 0;
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) ?? 'null');
      if (saved?.url === url && Number.isFinite(saved.y) && saved.y >= 0)
        target = saved.y;
    } catch {
      /* optional history persistence */
    }
    let pending = target > 0;
    let y = target;
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
    if (!pending) window.scrollTo(0, 0);
    else observer?.observe(document.body);
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
  }, [location.key, scope, url]);
  useLayoutEffect(() => {
    settled.current = ready;
    restore.current?.();
  }, [ready]);
}
