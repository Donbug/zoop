import { useEffect, useEffectEvent } from 'react';
import type { Reload } from './useAsyncData';

const canRefresh = () =>
  document.visibilityState !== 'hidden' &&
  !document.querySelector('[data-admin-editing="true"]');

// A-ADM-01/02/03/04/04b: prototype admin/api.ts refetchInterval.
// 숨겨진 문서·열린 변경 폼에서는 자동 읽기를 멈춰요.
export function useAdminRefresh(reload: Reload, interval: number | false) {
  const refresh = useEffectEvent(() =>
    reload({ quiet: true, accept: canRefresh }),
  );
  useEffect(() => {
    if (!interval) return;
    const timer = window.setInterval(() => {
      if (!canRefresh()) return;
      refresh();
    }, interval);
    return () => window.clearInterval(timer);
  }, [interval]);
}
