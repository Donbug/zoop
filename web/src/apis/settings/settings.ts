import { call } from '@/apis/auth/ApiService';
import type { MemberSettings, SettingsUpdate } from '@/types/settings';

// 목표 계약(docs/api/openapi.yaml)의 응답은 ApiResponse로 감싸지 않은 본문 그대로다.
// 인증·응답 래퍼 계약이 아직 정해지지 않아 공통 call()을 그대로 쓰고 응답 타입만 여기서 정한다.
// call()은 실패 시 상태 문구만 담은 Error를 던지므로 `{ error: { code } }`의
// 오류 코드(예: 409 version_conflict)를 구분할 수 없다. 화면은 공통 실패 안내와 다시 시도를 보여 준다.

const SETTINGS_API = '/api/v1/me/settings';

/** SettingsResponse. metadata는 화면에서 쓰지 않아 생략한다. */
type SettingsResponse = MemberSettings;

export function getSettings(): Promise<MemberSettings> {
  return call<SettingsResponse>(SETTINGS_API, 'GET');
}

export function updateSettings(
  request: SettingsUpdate,
): Promise<MemberSettings> {
  return call<SettingsResponse>(SETTINGS_API, 'PUT', request);
}
