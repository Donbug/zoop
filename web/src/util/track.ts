import { useEffect, useState } from 'react';
import { createIdempotencyKey } from '@/apis/portfolio/portfolio';
import { recordInteractionEvents } from '@/apis/telemetry/telemetry';
import { useAuthStore } from '@/stores/useAuthStore';
import type { TelemetryEvent } from '@/types/telemetry';

// 사용 이벤트 계측(FS065). 이벤트를 모아 한 번에 보내고, 실패는 무시한다(화면 동작에 영향을 주지 않는다).
// 세션(CSRF 토큰)이 없으면 보내지 않는다. 한 번의 화면 노출은 viewId 하나로 묶는다.

const MAX_BATCH = 20;
const FLUSH_DELAY_MS = 2000;
const ID_PATTERN = /^[A-Za-z0-9._:/-]{1,100}$/;

let queue: TelemetryEvent[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;

function transmit(events: TelemetryEvent[]) {
  if (!useAuthStore.getState().session?.csrfToken) return;
  recordInteractionEvents(events, createIdempotencyKey()).catch(() => {
    // 계측 실패는 무시한다.
  });
}

export function flushTelemetry() {
  clearTimeout(timer);
  timer = undefined;
  while (queue.length > 0) transmit(queue.splice(0, MAX_BATCH));
}

/** 이벤트를 큐에 넣는다. 서버가 거부할 모양(쓸 수 없는 id)은 보내지 않는다. */
export function track(event: TelemetryEvent) {
  if ('targetId' in event && !ID_PATTERN.test(event.targetId)) return;
  queue.push(event);
  if (queue.length >= MAX_BATCH) flushTelemetry();
  else timer ??= setTimeout(flushTelemetry, FLUSH_DELAY_MS);
}

/** 테스트용: 보내지 않은 이벤트를 비운다. */
export function resetTelemetry() {
  clearTimeout(timer);
  timer = undefined;
  queue = [];
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushTelemetry();
  });
}

function newViewId() {
  return createIdempotencyKey();
}

/** 화면이 열릴 때 노출 이벤트를 한 번 보내고, 이 노출의 viewId를 돌려준다. */
export function useScreenView(screen: 'main' | 'briefing') {
  const [viewId] = useState(newViewId);
  useEffect(() => {
    track({ type: 'screen_view', screen, viewId });
  }, [screen, viewId]);
  return viewId;
}
