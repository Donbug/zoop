// 사용자 행동 계측(요구 74): 이벤트를 모아 한 번에 보내고, 실패는 무시한다(화면 동작에 영향을 주지 않는다).
// 서버가 허용한 이벤트 종류·필드만 보낼 수 있다. 이름·이메일·입력한 글을 담을 칸이 없다.
// 한 번의 화면 노출은 viewId 하나로 묶는다(노출 중 노드를 골랐는지 가리는 비율 계산용).
import { useEffect, useState } from "react";

export type TrackEvent =
  | { type: "screen_view"; screen: "main" | "briefing"; viewId: string }
  | { type: "graph_node_select" | "graph_edge_select"; targetId: string; viewId?: string }
  | { type: "briefing_view"; targetId: string; viewId?: string }
  | { type: "briefing_issue_open"; targetId: string; roundId: string; viewId?: string };

const ENDPOINT = "/api/telemetry";
const MAX_BATCH = 20;
const FLUSH_DELAY_MS = 2000;
const ID_PATTERN = /^[A-Za-z0-9._:/-]{1,100}$/;

let queue: TrackEvent[] = [];
let timer: number | undefined;

function transmit(events: TrackEvent[]) {
  const body = JSON.stringify({ events });
  try {
    if (navigator.sendBeacon?.(ENDPOINT, new Blob([body], { type: "application/json" }))) return;
    void fetch(ENDPOINT, { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true, credentials: "same-origin" }).catch(() => {});
  } catch {
    // 계측 실패는 무시한다.
  }
}

function flush() {
  window.clearTimeout(timer);
  timer = undefined;
  while (queue.length > 0) transmit(queue.splice(0, MAX_BATCH));
}

/** 이벤트를 큐에 넣는다. 서버가 거부할 모양(주소에 쓸 수 없는 id)은 보내지 않는다. */
export function track(event: TrackEvent) {
  if ("targetId" in event && !ID_PATTERN.test(event.targetId)) return;
  queue.push(event);
  if (queue.length >= MAX_BATCH) flush();
  else timer ??= window.setTimeout(flush, FLUSH_DELAY_MS);
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });
  window.addEventListener("pagehide", flush);
}

function newViewId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `v${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

/** 화면이 열릴 때 노출 이벤트를 한 번 보내고, 이 노출의 viewId를 돌려준다. */
export function useScreenView(screen: "main" | "briefing"): string {
  const [viewId] = useState(newViewId);
  useEffect(() => {
    track({ type: "screen_view", screen, viewId });
  }, [screen, viewId]);
  return viewId;
}

/** 새 노출 id(브리핑 회차를 열 때마다 하나). */
export function useViewId(): string {
  return useState(newViewId)[0];
}
