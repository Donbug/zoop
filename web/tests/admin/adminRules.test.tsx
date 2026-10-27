import { act, fireEvent, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import PipelineReview from '@/components/admin/pipeline/PipelineReview';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type { PublicationRule } from '@/types/admin/rules';
import {
  createFakeServer,
  json,
  apiError,
  deferred,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const PATH = '/api/v1/admin/pipeline/rules';
const SWITCH = `${PATH}/:ruleId`;
// A-ADM-03: synthetic contract fixtures, no live rule mutation.
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
const rule = (id = 'single-source@1', enabled = false): PublicationRule => ({
  id,
  title: id === 'single-source@1' ? '단일 출처 숨기기' : '전망 숨기기',
  summary: '출처가 적은 관계를 숨겨요.',
  enabled,
  defaultEnabled: false,
  changedAt: null,
  changedBy: null,
  reason: null,
  eligible: null,
  publishedCandidates: null,
  publishedEvents: null,
  history: [],
});
let server: FakeServer;
function open(path = '/admin/pipeline?tab=rules') {
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
beforeEach(() => {
  useAdminSessionStore.getState().setSession(session);
  server = createFakeServer();
  server.on('GET', '/api/v1/admin/graph/versions', () =>
    json({
      items: [],
      activations: [],
      activeVersionId: null,
      nextCursor: null,
    }),
  );
  server.on('GET', PATH, () =>
    json({
      items: [rule(), rule('speculative-issue@1')],
      asOf: '2026-10-27T01:00:00Z',
      nextCursor: null,
    }),
  );
});

describe('A-ADM-03 자동 검수 규칙 · 66', () => {
  test('목록·null 집계·기본 상태·최신순 이력과 불투명 커서', async () => {
    server.on('GET', PATH, ({ query }) =>
      json({
        items: query.has('cursor')
          ? [rule('speculative-issue@1')]
          : [
              {
                ...rule(),
                changedAt: '2026-10-27T01:00:00Z',
                changedBy: 'admin@zoop.test',
                reason: '최신 사유',
                history: [
                  {
                    id: 2,
                    enabled: true,
                    changedAt: '2026-10-27T01:00:00Z',
                    adminEmail: 'a@zoop.test',
                    reason: '최근 이력',
                  },
                  {
                    id: 1,
                    enabled: false,
                    changedAt: '2026-10-26T01:00:00Z',
                    adminEmail: 'a@zoop.test',
                    reason: '이전 이력',
                  },
                ],
              },
            ],
        asOf: '2026-10-27T01:00:00Z',
        nextCursor: query.has('cursor') ? null : 'signed+/cursor',
      }),
    );
    const { user } = open();
    const panel = await screen.findByRole('region', { name: '자동 검수 규칙' });
    expect(
      await within(panel).findByText(
        /다루는 보류 후보 – · 활성 버전 공개 사건 – · 공개 후보 –/,
      ),
    ).toBeTruthy();
    const history = within(panel).getByText(/전환 이력 2건/);
    await user.click(history);
    const entries = within(history.parentElement!).getAllByRole('listitem');
    expect(entries[0].textContent).toContain('최근 이력');
    expect(entries[1].textContent).toContain('이전 이력');
    await user.click(within(panel).getByRole('button', { name: '더 보기' }));
    expect(await within(panel).findByText('전망 숨기기 · 꺼짐')).toBeTruthy();
    expect(server.calls('GET', PATH).at(-1)?.query.get('cursor')).toBe(
      'signed+/cursor',
    );
    expect(server.calls('GET', PATH)[0].query.get('limit')).toBe('50');
  });
  test('사유 필수·500자 제한·전환 본문과 관리자 CSRF·다음 버전 안내', async () => {
    server.on('PUT', SWITCH, () =>
      json({
        rule: rule(undefined, true),
        idempotent: false,
        reviewRevision: 3,
      }),
    );
    const { user } = open();
    await user.click(
      await screen.findByRole('button', { name: '단일 출처 숨기기 규칙 켜기' }),
    );
    const form = screen.getByRole('form', {
      name: '단일 출처 숨기기 전환 사유',
    });
    const submit = within(form).getByRole('button', { name: '규칙 켜기 확인' });
    await user.click(submit);
    expect(within(form).getByRole('alert')).toBeTruthy();
    expect(server.calls('PUT', SWITCH)).toHaveLength(0);
    const input = within(form).getByLabelText(
      '전환 사유',
    ) as HTMLTextAreaElement;
    expect(input.maxLength).toBe(500);
    fireEvent.change(input, { target: { value: 'x'.repeat(501) } });
    await user.click(submit);
    expect(server.calls('PUT', SWITCH)).toHaveLength(0);
    fireEvent.change(input, { target: { value: ' 검토 완료 ' } });
    expect(within(form).getByText('7/500자')).toBeTruthy();
    await user.click(submit);
    expect(
      await screen.findByText('규칙을 켰어요. 다음 그래프 버전부터 반영돼요.'),
    ).toBeTruthy();
    const request = server.calls('PUT', SWITCH)[0];
    expect(request.params.ruleId).toBe('single-source@1');
    expect(request.body).toEqual({ enabled: true, reason: '검토 완료' });
    expect(request.headers.get('X-CSRF-Token')).toBe('test-admin-csrf');
    expect(request.headers.has('Idempotency-Key')).toBe(false);
  });
  test('요청 중 다른 규칙과 재제출 잠금·탭 숨김 뒤 결과 유지·idempotent 안내', async () => {
    const pending = deferred<Response>();
    server.on('PUT', SWITCH, () => pending.promise);
    const { user, location } = open();
    await user.click(
      await screen.findByRole('button', { name: '단일 출처 숨기기 규칙 켜기' }),
    );
    await user.type(screen.getByLabelText('전환 사유'), '상태 확인');
    await user.click(screen.getByRole('button', { name: '규칙 켜기 확인' }));
    expect(
      (
        screen.getByRole('button', {
          name: '전망 숨기기 규칙 켜기',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.submit(screen.getByRole('form'));
    expect(server.calls('PUT', SWITCH)).toHaveLength(1);
    await user.click(screen.getByRole('tab', { name: '후보' }));
    expect(location()).toContain('tab=candidates');
    await act(async () =>
      pending.resolve(
        json({
          rule: rule(undefined, true),
          idempotent: true,
          reviewRevision: 2,
        }),
      ),
    );
    await user.click(screen.getByRole('tab', { name: '규칙' }));
    expect(
      await screen.findByText(
        '이미 같은 상태예요. 다음 그래프 버전부터 반영돼요.',
      ),
    ).toBeTruthy();
  });
  test.each([409, 422])(
    '%s 오류에는 사유를 보존하고 다시 시도해요',
    async (status) => {
      server.on('PUT', SWITCH, () =>
        apiError(
          status,
          status === 409 ? 'REVISION_CONFLICT' : 'INVALID_REQUEST',
        ),
      );
      const { user } = open();
      await user.click(
        await screen.findByRole('button', {
          name: '단일 출처 숨기기 규칙 켜기',
        }),
      );
      await user.type(screen.getByLabelText('전환 사유'), '사유 유지');
      await user.click(screen.getByRole('button', { name: '규칙 켜기 확인' }));
      expect((await screen.findByRole('alert')).textContent).toContain(
        status === 409 ? '규칙 상태가 달라졌어요' : '사유와 규칙 정보를 확인',
      );
      expect(
        (screen.getByLabelText('전환 사유') as HTMLTextAreaElement).value,
      ).toBe('사유 유지');
      expect(
        (
          screen.getByRole('button', {
            name: '규칙 켜기 확인',
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false);
    },
  );
  test('목록 실패 재시도·빈 결과', async () => {
    server.on('GET', PATH, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = open();
    expect(await screen.findByRole('alert')).toBeTruthy();
    server.on('GET', PATH, () =>
      json({ items: [], asOf: '2026-10-27T01:00:00Z', nextCursor: null }),
    );
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('등록된 규칙이 없어요.')).toBeTruthy();
  });
  test('관리자 교체 뒤 도착한 전환 응답을 새 관리자 화면에 반영하지 않아요', async () => {
    const pending = deferred<Response>();
    server.on('PUT', SWITCH, () => pending.promise);
    const { user } = open();
    await user.click(
      await screen.findByRole('button', { name: '단일 출처 숨기기 규칙 켜기' }),
    );
    await user.type(screen.getByLabelText('전환 사유'), '이전 관리자');
    await user.click(screen.getByRole('button', { name: '규칙 켜기 확인' }));
    act(() =>
      useAdminSessionStore
        .getState()
        .setSession({ ...session, admin: { ...session.admin!, id: 'a2' } }),
    );
    await screen.findByRole('button', { name: '단일 출처 숨기기 규칙 켜기' });
    await act(async () =>
      pending.resolve(
        json({
          rule: rule(undefined, true),
          idempotent: false,
          reviewRevision: 5,
        }),
      ),
    );
    expect(
      screen.queryByText('규칙을 켰어요. 다음 그래프 버전부터 반영돼요.'),
    ).toBeNull();
    expect(screen.queryByRole('form')).toBeNull();
  });
});

test('A-ADM-03 관리자 세션 없이는 규칙을 조회하지 않아요', async () => {
  useAdminSessionStore.getState().clearSession();
  open();
  expect(await screen.findByText('관리자 로그인')).toBeTruthy();
  expect(server.calls('GET', PATH)).toHaveLength(0);
});
test('A-ADM-03 규칙 목록 401은 관리자 로그인으로 이동해요', async () => {
  server.on('GET', PATH, () => apiError(401, 'AUTH_REQUIRED'));
  open();
  expect(await screen.findByText('관리자 로그인')).toBeTruthy();
});
