import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Session } from '@/types/auth';
import { flushTelemetry, resetTelemetry, track } from '@/util/track';
import { createFakeServer, json, type FakeServer } from '../support/fakeServer';

const TELEMETRY = '/api/v1/telemetry';

const guest: Session = {
  authenticated: false,
  kind: 'guest',
  user: null,
  setup: null,
  csrfToken: 'csrf-guest',
  expiresAt: null,
};

let server: FakeServer;

beforeEach(() => {
  resetTelemetry();
  useAuthStore.getState().clearSession();
  server = createFakeServer();
  server.on('POST', TELEMETRY, () => json({ accepted: 2 }, 202));
});

afterEach(() => resetTelemetry());

describe('FS065 사용 이벤트 계측', () => {
  test('모은 이벤트를 한 번에 보내고 CSRF·Idempotency-Key를 붙인다', async () => {
    useAuthStore.getState().setSession(guest);
    track({ type: 'screen_view', screen: 'main', viewId: 'view-0001' });
    track({
      type: 'graph_node_select',
      targetId: 'samsung',
      viewId: 'view-0001',
    });
    flushTelemetry();

    await expect.poll(() => server.calls('POST', TELEMETRY).length).toBe(1);
    expect(server.calls('POST', TELEMETRY)[0].body).toEqual({
      events: [
        { type: 'screen_view', screen: 'main', viewId: 'view-0001' },
        { type: 'graph_node_select', targetId: 'samsung', viewId: 'view-0001' },
      ],
    });
    const init = (
      globalThis.fetch as unknown as {
        mock: { calls: [unknown, RequestInit][] };
      }
    ).mock.calls[0][1];
    const headers = new Headers(init.headers);
    expect(headers.get('X-CSRF-Token')).toBe('csrf-guest');
    expect(headers.get('Idempotency-Key')).toBeTruthy();
  });

  test('세션이 없거나 쓸 수 없는 id면 보내지 않는다', () => {
    track({ type: 'graph_node_select', targetId: 'samsung' });
    flushTelemetry();
    useAuthStore.getState().setSession(guest);
    track({ type: 'graph_node_select', targetId: 'has space' });
    flushTelemetry();

    expect(server.calls('POST', TELEMETRY)).toHaveLength(0);
  });

  test('D-BRF-01·02 discards queued activity when the session changes', async () => {
    useAuthStore.getState().setSession(guest);
    track({ type: 'briefing_view', targetId: 'old-round', viewId: 'old-view' });
    useAuthStore.getState().setSession({ ...guest, csrfToken: 'new-csrf' });
    flushTelemetry();
    expect(server.calls('POST', TELEMETRY)).toHaveLength(0);
    track({ type: 'briefing_view', targetId: 'new-round', viewId: 'new-view' });
    flushTelemetry();
    await expect.poll(() => server.calls('POST', TELEMETRY).length).toBe(1);
    expect(server.calls('POST', TELEMETRY)[0].body).toEqual({
      events: [
        { type: 'briefing_view', targetId: 'new-round', viewId: 'new-view' },
      ],
    });
  });
});
