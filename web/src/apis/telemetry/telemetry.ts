import { call } from '@/apis/auth/ApiService';
import type { TelemetryEvent } from '@/types/telemetry';

// FS065 사용 이벤트 접수 (recordInteractionEvents, POST /api/v1/telemetry → 202 { accepted }).
// 세션 CSRF와 Idempotency-Key가 필요하다. 계측 401이 회원 세션을 지우지 않도록 skipAuth로 보낸다.
export function recordInteractionEvents(
  events: TelemetryEvent[],
  idempotencyKey: string,
) {
  return call<{ accepted: number }>(
    '/api/v1/telemetry',
    'POST',
    { events },
    // 화면을 닫을 때 보내는 마지막 묶음도 끝까지 전송되도록 keepalive로 보낸다.
    {
      skipAuth: true,
      keepalive: true,
      headers: { 'Idempotency-Key': idempotencyKey },
    },
  );
}
