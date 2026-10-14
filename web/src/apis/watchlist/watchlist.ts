import { call } from '@/apis/auth/ApiService';
import type { MemberSettings } from '@/types/settings';

// PUT /api/v1/me/watchlist/{id} {watched}: 원하는 최종 상태를 보낸다(다시 보내도 한 번만 반영).
// 응답은 ApiResponse로 감싸지 않은 SettingsResponse다(metadata는 생략).
// 공통 call()은 실패 시 상태 문구만 담은 Error를 던지므로 오류 코드를 구분하지 않는다.

type SettingsResponse = MemberSettings;

export function setWatched(
  companyId: string,
  watched: boolean,
): Promise<MemberSettings> {
  return call<SettingsResponse>(
    `/api/v1/me/watchlist/${encodeURIComponent(companyId)}`,
    'PUT',
    { watched },
  );
}
