import { useCallback } from 'react';
import { getSettings } from '@/apis/settings/settings';
import { useAuthStore, selectMemberId } from '@/stores/useAuthStore';
import { useAsyncData } from './useAsyncData';

/** D-COM-01: share the catalog's member settings with the company header. */
export function useCompanySettings(enabled = true) {
  const member = useAuthStore(selectMemberId);
  const revision = useAuthStore((s) => s.sessionRevision);
  return useAsyncData(
    useCallback(async () => {
      if (!enabled || !member) return null;
      const settings = await getSettings();
      const current = useAuthStore.getState();
      if (
        current.sessionRevision !== revision ||
        selectMemberId(current) !== member
      )
        throw new Error('계정이 변경됐어요.');
      return settings;
    }, [enabled, member, revision]),
  );
}
