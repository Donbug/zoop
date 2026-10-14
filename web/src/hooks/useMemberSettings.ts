import { useCallback, useState } from 'react';
import { getSettings, updateSettings } from '@/apis/settings/settings';
import { useAsyncData } from './useAsyncData';
import type { MemberSettings, SettingsPatch } from '@/types/settings';

/** 회원 설정 조회와 저장. 저장 중·실패 상태를 함께 돌려준다. */
export function useMemberSettings() {
  const settings = useAsyncData(getSettings);
  const { setData } = settings;
  const version = settings.data?.version;
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  const save = useCallback(
    async (patch: SettingsPatch): Promise<MemberSettings | null> => {
      if (version === undefined) return null;
      setSaving(true);
      setSaveFailed(false);
      try {
        const saved = await updateSettings({ version, ...patch });
        setData(saved);
        return saved;
      } catch {
        setSaveFailed(true);
        // 오류 코드를 읽을 수 없어 버전 충돌(409)인지 알 수 없다.
        // 다음 다시 시도가 최신 version으로 가도록 설정을 조용히 다시 읽는다.
        try {
          setData(await getSettings());
        } catch {
          // 다시 읽기도 실패하면 기존 version으로 다시 시도한다.
        }
        return null;
      } finally {
        setSaving(false);
      }
    },
    [version, setData],
  );

  return { settings, save, saving, saveFailed };
}
