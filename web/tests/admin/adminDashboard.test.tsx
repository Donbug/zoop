import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminDashboardPage from '@/pages/admin/dashboard/AdminDashboardPage';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type { Dashboard } from '@/types/admin/dashboard';
import {
  apiError,
  createFakeServer,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const DASHBOARD = '/api/v1/admin/dashboard';
const SESSION = '/api/v1/admin/auth/session';

const signedIn: AdminSession = {
  authenticated: true,
  expired: false,
  expiredReason: null,
  admin: {
    id: 'adm-1',
    email: 'admin@zoop.test',
    displayName: '운영 관리자',
    role: 'operator',
  },
  expiresAt: '2099-01-01T08:00:00Z',
  idleExpiresAt: '2099-01-01T00:30:00Z',
  idleTimeoutSeconds: 1800,
  absoluteTimeoutSeconds: 28800,
  csrfToken: 'csrf-admin',
};

// 합성 fixture. 와이어프레임 A-ADM-01의 예시 수치를 따른다.
function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    generatedAt: '2026-10-06T03:43:56Z',
    metadata: { partial: false, failures: [] },
    ledger: { status: 'connected', error: null },
    graph: {
      activeVersionId: 'v1',
      activatedAt: '2026-10-01T11:27:00Z',
      versionCount: 1,
      activeVersion: null,
      reviewRevision: 11,
      reviewDecisions: 13,
      rules: [
        {
          id: 'R1@2',
          title: '역할 문구 미확인',
          enabled: true,
          publishedEvents: 43,
        },
      ],
      graphDb: { status: 'reflected', pendingJobs: 0 },
    },
    candidates: {
      allow: 102,
      hold: 304,
      reject: 1,
      inactive: 0,
      holdPendingReview: 260,
    },
    jobs: { running: 0, queued: 0, failed24h: 0, recent: [] },
    ai: {
      window: '7d',
      requests: 28,
      succeeded: 28,
      failed: 0,
      features: [
        { feature: 'chat', label: 'AI 챗봇', requests: 2, failed: 0 },
        {
          feature: 'briefing',
          label: '출퇴근 브리핑',
          requests: 26,
          failed: 0,
        },
      ],
    },
    briefings: {
      latest: [
        {
          id: 'r-1',
          date: '2026-10-06',
          edition: 'morning',
          status: 'published',
          dataWindow: { end: '2026-10-05T22:40:00Z' },
        },
        {
          id: 'r-2',
          date: '2026-10-05',
          edition: 'evening',
          status: 'failed',
          dataWindow: { end: '2026-10-05T09:10:00Z' },
        },
      ],
      delayedOrFailed: 1,
    },
    members: {
      registered: 3,
      activeMemberSessions: 8,
      activeGuestSessions: 0,
      source: 'zoop-db',
    },
    audit: { last24h: 3 },
    ...overrides,
  };
}

function openDashboard() {
  return renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [{ path: '/admin', element: <AdminDashboardPage /> }],
      },
      { path: '/admin/login', element: <p>관리자 로그인 화면</p> },
      { path: '/admin/briefings', element: <p>브리핑 운영 화면</p> },
    ],
    '/admin',
  );
}

let server: FakeServer;

beforeEach(() => {
  useAdminSessionStore.setState({
    status: 'checking',
    session: null,
    admin: null,
    revision: 0,
  });
  server = createFakeServer();
  server.on('GET', SESSION, () => json(signedIn));
});

describe('A-ADM-01 운영 대시보드 (FS072)', () => {
  test('요약 지표 5개와 각 영역을 와이어프레임대로 보여 준다', async () => {
    server.on('GET', DASHBOARD, () => json(dashboard()));
    openDashboard();

    expect(await screen.findByText('260건')).toBeTruthy();
    expect(screen.getByText('통과 102 · 보류 304 · 폐기 1')).toBeTruthy();
    expect(screen.getByText('v1')).toBeTruthy();
    expect(
      screen.getByText(/자동 검수 규칙 R1@2 켜짐 · 게시 사건 43건/),
    ).toBeTruthy();
    expect(screen.getByText('반영됨')).toBeTruthy();
    expect(screen.getByText('대기 작업 0건')).toBeTruthy();
    expect(screen.getByText('실행 0 · 대기 0')).toBeTruthy();
    expect(screen.getByText('성공 28 · 실패 0')).toBeTruthy();
    expect(screen.getByText('갱신 2026-10-06 12:43 KST')).toBeTruthy();

    const briefings = screen.getByRole('table', { name: '브리핑 회차 목록' });
    expect(within(briefings).getByText('2026-10-06 출근')).toBeTruthy();
    expect(within(briefings).getByText('발행됨')).toBeTruthy();
    expect(within(briefings).getByText('2026-10-06 07:40 KST')).toBeTruthy();
    expect(within(briefings).getByText('실패')).toBeTruthy();
    expect(
      screen.getByText('늦게 발행됐거나 실패한 회차가 1건 있어요.'),
    ).toBeTruthy();

    const ai = screen.getByRole('table', { name: 'AI 기능별 요청' });
    expect(within(ai).getByText('출퇴근 브리핑')).toBeTruthy();
    expect(within(ai).getByText('26')).toBeTruthy();

    const usage = screen.getByRole('region', { name: '이용 현황' });
    expect(within(usage).getByText('비회원 0')).toBeTruthy();
  });

  test('관리 화면으로 가는 링크를 제공한다', async () => {
    server.on('GET', DASHBOARD, () => json(dashboard()));
    const { user, location } = openDashboard();

    await screen.findByText('260건');
    expect(
      screen.getByRole('link', { name: '작업 관제 →' }).getAttribute('href'),
    ).toBe('/admin/pipeline');
    expect(
      screen.getByRole('link', { name: 'AI 운영 →' }).getAttribute('href'),
    ).toBe('/admin/ai');
    expect(
      screen.getByRole('link', { name: '감사 로그 →' }).getAttribute('href'),
    ).toBe('/admin/audit');

    await user.click(screen.getByRole('link', { name: '브리핑 운영 →' }));
    expect(location()).toBe('/admin/briefings');
  });

  test('조회 중에는 불러오는 중이라고 알린다', async () => {
    server.on('GET', DASHBOARD, () => new Promise<Response>(() => {}));
    openDashboard();

    expect(await screen.findByText('대시보드를 불러오고 있어요')).toBeTruthy();
  });

  test('영역에 자료가 없으면 영역마다 빈 상태를 보여 준다', async () => {
    server.on('GET', DASHBOARD, () =>
      json(
        dashboard({
          briefings: { latest: [], delayedOrFailed: 0 },
          ai: {
            window: '7d',
            requests: 0,
            succeeded: 0,
            failed: 0,
            features: [],
          },
        }),
      ),
    );
    openDashboard();

    expect(await screen.findByText('아직 브리핑 회차가 없어요.')).toBeTruthy();
    expect(screen.getByText('아직 실행한 작업이 없어요.')).toBeTruthy();
    expect(screen.getByText('최근 7일 동안 AI 요청이 없어요.')).toBeTruthy();
  });

  test('원장에 연결하지 못하면 검수 대기를 비우고 사유를 알린다', async () => {
    server.on('GET', DASHBOARD, () =>
      json(
        dashboard({
          ledger: {
            status: 'unavailable',
            error: { code: 'SOURCE_UNAVAILABLE', message: '원장 응답 없음' },
          },
          candidates: null,
          graph: { ...dashboard().graph!, graphDb: null },
        }),
      ),
    );
    openDashboard();

    expect(
      await screen.findByText(
        '원장에 연결하지 못해 검수 현황을 표시하지 못했어요. (원장 응답 없음)',
      ),
    ).toBeTruthy();
    expect(screen.getByText('원장에 연결하지 못했어요')).toBeTruthy();
    expect(screen.getByText('확인 불가')).toBeTruthy();
  });

  test('최신 API의 부분 응답은 누락 영역을 0으로 꾸미거나 렌더링에 실패하지 않는다', async () => {
    server.on('GET', DASHBOARD, () =>
      json(
        dashboard({
          metadata: {
            partial: true,
            failures: [
              {
                source: 'jobs',
                code: 'SOURCE_UNAVAILABLE',
                message: 'not connected',
              },
            ],
          },
          jobs: null,
          ai: null,
          briefings: null,
          members: null,
          audit: null,
        }),
      ),
    );
    openDashboard();

    expect(await screen.findByText('작업 원장을 읽지 못했어요.')).toBeTruthy();
    expect(screen.getByText('AI 요청 원장을 읽지 못했어요.')).toBeTruthy();
    expect(screen.getByText('브리핑 원장을 읽지 못했어요.')).toBeTruthy();
    expect(screen.getAllByText('–').length).toBeGreaterThan(0);
  });

  test('조회에 실패하면 다시 시도할 수 있다', async () => {
    let attempts = 0;
    server.on('GET', DASHBOARD, () => {
      attempts += 1;
      return attempts === 1
        ? apiError(500, 'INTERNAL_ERROR')
        : json(dashboard());
    });
    const { user } = openDashboard();

    const alert = await screen.findByRole('alert');
    expect(
      within(alert).getByText('대시보드를 불러오지 못했어요'),
    ).toBeTruthy();
    await user.click(within(alert).getByRole('button', { name: '다시 시도' }));

    expect(await screen.findByText('260건')).toBeTruthy();
    expect(server.calls('GET', DASHBOARD)).toHaveLength(2);
  });

  test('권한이 없으면(403) 권한 안내를 보여 준다', async () => {
    server.on('GET', DASHBOARD, () => apiError(403, 'ACCESS_DENIED'));
    openDashboard();

    expect(
      await screen.findByText(
        '대시보드를 볼 권한이 없어요. 관리자 권한을 확인해 주세요.',
      ),
    ).toBeTruthy();
  });

  test('관리자 세션이 만료되면(401) 관리자 로그인으로 보낸다', async () => {
    server.on('GET', DASHBOARD, () => apiError(401, 'AUTH_REQUIRED'));
    const { location } = openDashboard();

    expect(await screen.findByText('관리자 로그인 화면')).toBeTruthy();
    expect(location()).toBe('/admin/login');
    expect(useAdminSessionStore.getState().admin).toBeNull();
  });

  test('새로 고침은 대시보드를 다시 조회한다', async () => {
    server.on('GET', DASHBOARD, () => json(dashboard()));
    const { user } = openDashboard();

    await screen.findByText('260건');
    await user.click(screen.getByRole('button', { name: '새로 고침' }));
    await screen.findByText('260건');
    expect(server.calls('GET', DASHBOARD)).toHaveLength(2);
  });
});
