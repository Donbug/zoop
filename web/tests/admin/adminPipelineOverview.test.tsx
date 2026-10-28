import { act, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import PipelineReview from '@/components/admin/pipeline/PipelineReview';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';
import { OVERVIEW, overview, onOverview } from '../support/adminPipeline';

// A-ADM-03 이슈 관제 개요 (FS058·FS059·FS063·FS067-01). 합성 계약 픽스처만 쓴다.
const session: AdminSession = {
  authenticated: true,
  expired: false,
  expiredReason: null,
  admin: {
    id: 'a1',
    email: 'admin@zoop.test',
    displayName: '관리자',
    role: 'operator',
  },
  expiresAt: '2099-01-01T00:00:00Z',
  idleExpiresAt: '2099-01-01T00:00:00Z',
  idleTimeoutSeconds: 1800,
  absoluteTimeoutSeconds: 28800,
  csrfToken: 'test-admin-csrf',
};
let server: FakeServer;
function open(path = '/admin/pipeline') {
  return renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [{ path: '/admin/pipeline', element: <PipelineReview /> }],
      },
      { path: '/admin/login', element: <p>관리자 로그인</p> },
    ],
    path,
  );
}
const metric = (label: string) =>
  screen.getByText(label, { selector: 'dt' }).parentElement as HTMLElement;

beforeEach(() => {
  useAdminSessionStore.getState().setSession(session);
  server = createFakeServer();
  // 탭 위 자동 검수 규칙과 기본 후보 탭은 빈 응답. 개요는 테스트마다 따로 등록한다.
  onOverview(server);
  server.on('GET', '/api/v1/admin/graph/versions', () =>
    json({
      items: [],
      activations: [],
      activeVersionId: null,
      nextCursor: null,
    }),
  );
  server.on('GET', '/api/v1/admin/pipeline/jobs', () =>
    json({ items: [], nextCursor: null, asOf: '2026-10-28T01:00:00Z' }),
  );
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    value: 'visible',
  });
});
afterEach(() => {
  vi.useRealTimers();
});

describe('A-ADM-03 이슈 관제 개요 · 65', () => {
  test('후보 판정·검수 대기·공개 버전·작업 요약을 보여 주고 작업 로그로 옮긴다', async () => {
    server.on('GET', OVERVIEW, () => json(overview()));
    const { location } = open();

    const region = await screen.findByRole('region', {
      name: '이슈 관제 개요',
    });
    expect(within(metric('후보 판정')).getByText('12건')).toBeTruthy();
    expect(metric('후보 판정').textContent).toContain(
      '통과 7 · 보류 3 · 폐기 2',
    );
    expect(within(metric('검수 대기(보류)')).getByText('3건')).toBeTruthy();
    expect(metric('사용자에게 보이는 버전').textContent).toContain(
      'v-20261028',
    );
    expect(metric('GraphDB 반영').textContent).toContain('반영됨');
    expect(region.textContent).toContain(
      '실행 중 1 · 대기 0 · 24시간 실패 1건',
    );
    expect(region.textContent).toContain('최근 실패 기사 분석');
    expect(region.textContent).toContain('미해결 수집 실패 2건');

    fireEvent.click(
      within(region).getByRole('button', { name: '작업 로그 보기' }),
    );
    expect(location()).toBe('/admin/pipeline?tab=jobs');
  });

  test('활성 버전이 없으면 –로 표시하고 0으로 꾸미지 않는다', async () => {
    server.on('GET', OVERVIEW, () =>
      json(
        overview({
          publication: {
            activeVersionId: null,
            ledgerMatchesActive: false,
            issuesOnlyInLedger: [],
            issuesOnlyInActive: [],
          },
          projection: {
            status: 'unavailable',
            pendingJobs: null,
            oldestPendingAt: null,
            lastCompletedAt: null,
            neo4j: null,
            checkedAt: '2026-10-28T01:00:00Z',
          },
        }),
      ),
    );
    open();

    await screen.findByRole('region', { name: '이슈 관제 개요' });
    expect(metric('사용자에게 보이는 버전').textContent).toContain('–');
    expect(metric('사용자에게 보이는 버전').textContent).toContain(
      '활성 버전이 없어요',
    );
    expect(metric('GraphDB 반영').textContent).toContain('확인 불가');
  });

  test('불러오지 못하면 오류와 다시 시도를 보여 준다', async () => {
    server.on('GET', OVERVIEW, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    open();

    expect(
      await screen.findByText('원장 상태를 불러오지 못했어요'),
    ).toBeTruthy();
    server.on('GET', OVERVIEW, () => json(overview()));
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(
      await screen.findByRole('region', { name: '이슈 관제 개요' }),
    ).toBeTruthy();
  });

  test('10초마다 조용히 다시 읽고, 실패하면 이전 결과를 유지한다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    server.on('GET', OVERVIEW, () => json(overview()));
    open();
    await screen.findByRole('region', { name: '이슈 관제 개요' });
    expect(server.calls('GET', OVERVIEW)).toHaveLength(1);

    server.on('GET', OVERVIEW, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(server.calls('GET', OVERVIEW)).toHaveLength(2);
    expect(within(metric('후보 판정')).getByText('12건')).toBeTruthy();
    expect(
      screen.getByText('새로 고치지 못했어요. 이전 결과를 표시해요.'),
    ).toBeTruthy();
  });

  test('관리자 세션이 바뀌면 이전 관리자의 개요를 숨기고 다시 읽는다', async () => {
    server.on('GET', OVERVIEW, () => json(overview()));
    open();
    await screen.findByRole('region', { name: '이슈 관제 개요' });

    const pending = deferred<Response>();
    server.on('GET', OVERVIEW, () => pending.promise);
    act(() => {
      useAdminSessionStore.getState().setSession(session);
    });
    expect(screen.queryByRole('region', { name: '이슈 관제 개요' })).toBeNull();
    expect(screen.getByText('원장 상태를 불러오고 있어요')).toBeTruthy();
    await act(async () => {
      pending.resolve(json(overview()));
    });
    expect(
      await screen.findByRole('region', { name: '이슈 관제 개요' }),
    ).toBeTruthy();
  });
});
