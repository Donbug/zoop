import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import AdminMembersPage from '@/pages/admin/members/AdminMembersPage';
import AdminMemberDetailPage from '@/pages/admin/members/AdminMemberDetailPage';
import AdminAuditPage from '@/pages/admin/audit/AdminAuditPage';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type {
  AuditEntry,
  MemberDetail,
  MemberRow,
} from '@/types/admin/members';
import {
  apiError,
  createFakeServer,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const SESSION = '/api/v1/admin/auth/session';
const MEMBERS = '/api/v1/admin/members';
const MEMBER = '/api/v1/admin/members/:memberId';
const BLOCK = '/api/v1/admin/members/:memberId/block';
const UNBLOCK = '/api/v1/admin/members/:memberId/unblock';
const AUDIT = '/api/v1/admin/audit-log';

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

// 이하 합성 fixture. 와이어프레임 A-ADM-05·05b의 예시를 따른다(가명 id·가린 이메일).
function member(overrides: Partial<MemberRow> = {}): MemberRow {
  return {
    id: 'M-EBF98301',
    emailMasked: 'd***@zoop.local',
    signupMethod: 'email',
    createdAt: '2026-10-01T11:27:00Z',
    lastActiveAt: '2026-10-06T03:43:00Z',
    status: 'active',
    statusRevision: 3,
    activity: {
      sessions: 6,
      graphSelections: 41,
      aiQuestions: 2,
      briefingViews: 0,
    },
    ...overrides,
  };
}

function detail(
  row: MemberRow,
  overrides: Partial<MemberDetail> = {},
): MemberDetail {
  return {
    member: row,
    onboardingCompleted: true,
    tutorialCompleted: false,
    watchlistCount: 3,
    holdingCount: 0,
    accountConnected: false,
    feedbackUp: 1,
    feedbackDown: 0,
    history: [],
    ...overrides,
  };
}

function audit(overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 1,
    at: '2026-10-06T03:43:55Z',
    actorKind: 'admin',
    actorId: 'adm-1',
    actorEmail: 'admin@zoop.local',
    action: 'auth.login',
    targetType: 'admin-session',
    targetId: 'admin-demo',
    reason: null,
    outcome: 'ok',
    detail: {},
    ...overrides,
  };
}

function headersOf(pathEnd: string) {
  const calls = (
    globalThis.fetch as unknown as {
      mock: { calls: [RequestInfo | URL, RequestInit | undefined][] };
    }
  ).mock.calls;
  return calls
    .filter(([input]) => String(input).endsWith(pathEnd))
    .map(([, init]) => new Headers(init?.headers));
}

function open(path: string) {
  return renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [
          { path: '/admin/members', element: <AdminMembersPage /> },
          {
            path: '/admin/members/:memberId',
            element: <AdminMemberDetailPage />,
          },
          { path: '/admin/audit', element: <AdminAuditPage /> },
        ],
      },
      { path: '/admin/login', element: <p>관리자 로그인 화면</p> },
    ],
    path,
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

describe('A-ADM-05 회원·접근 관리 (FS069)', () => {
  test('가명 id·가린 이메일·활동 요약과 상태별 인원을 보여 주고 상세로 간다', async () => {
    server.on('GET', MEMBERS, () =>
      json({
        items: [
          member(),
          member({
            id: 'M-A85C3F86',
            emailMasked: 's***@zoop.local',
            status: 'blocked',
            lastActiveAt: null,
          }),
        ],
        nextCursor: null,
        counts: { all: 2, active: 1, blocked: 1 },
      }),
    );
    server.on('GET', MEMBER, () => json(detail(member())));
    const { user, location } = open('/admin/members');

    const table = await screen.findByRole('table', { name: '회원 목록' });
    expect(within(table).getByText('d***@zoop.local')).toBeTruthy();
    expect(within(table).getAllByText('이메일')).toHaveLength(2);
    expect(within(table).getAllByText('41')).toHaveLength(2);
    expect(within(table).getByText('정상')).toBeTruthy();
    expect(within(table).getByText('차단됨')).toBeTruthy();
    expect(screen.getByText('전체 2명 · 정상 1 · 차단 1')).toBeTruthy();

    await user.click(within(table).getByRole('link', { name: 'M-EBF98301' }));
    expect(location()).toBe('/admin/members/M-EBF98301');
    expect(await screen.findByText('41회')).toBeTruthy();
    expect(screen.queryByText('1분 단위로 기록돼요')).toBeNull();
    expect(screen.queryByText('노드·간선')).toBeNull();
    expect(screen.queryByText('좋아요 / 싫어요')).toBeNull();
    expect(screen.queryByText('종목 이름은 보이지 않아요')).toBeNull();
    expect(screen.queryByText('가상 계좌 연결됨')).toBeNull();
    expect(screen.queryByText('가상 계좌 없음')).toBeNull();
    expect(screen.getByText('차단하거나 해제한 기록이 없어요.')).toBeTruthy();
  });

  test('상태 필터와 검색어로 다시 조회하고 주소에 남긴다', async () => {
    server.on('GET', MEMBERS, () =>
      json({
        items: [],
        nextCursor: null,
        counts: { all: 0, active: 0, blocked: 0 },
      }),
    );
    const { user, location } = open('/admin/members');
    expect(await screen.findByText('조건에 맞는 회원이 없어요.')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '차단됨' }));
    await user.type(
      screen.getByRole('searchbox', { name: '회원 검색' }),
      'M-A8',
    );

    await waitFor(() => {
      const query = server.calls('GET', MEMBERS).at(-1)?.query;
      expect(query?.get('status')).toBe('blocked');
      expect(query?.get('q')).toBe('M-A8');
    });
    expect(location()).toBe('/admin/members?status=blocked&q=M-A8');
  });

  test('사유를 받아 회원을 차단하고, 서버가 돌려준 상세로 바꾼다', async () => {
    server.on('GET', MEMBER, () => json(detail(member())));
    server.on('POST', BLOCK, () =>
      json({
        changed: true,
        detail: detail(member({ status: 'blocked' }), {
          history: [
            {
              at: '2026-10-06T04:00:00Z',
              action: 'member.block',
              reason: '이용 약관 위반',
              adminEmail: 'admin@zoop.test',
            },
          ],
        }),
      }),
    );
    const { user } = open('/admin/members/M-EBF98301');

    await user.click(await screen.findByRole('button', { name: '차단' }));
    const form = screen.getByRole('form', { name: '회원 차단' });
    expect(
      within(form).getByText(/열려 있는 모든 세션이 지금 끝나고/),
    ).toBeTruthy();
    await user.click(within(form).getByRole('button', { name: '차단하기' }));
    expect(
      within(form).getByText('사유를 1~500자로 입력해 주세요.'),
    ).toBeTruthy();
    const limitedReason = within(form).getByLabelText(
      '차단 사유(감사 로그에 남아요)',
    ) as HTMLTextAreaElement;
    expect(limitedReason.maxLength).toBe(500);
    fireEvent.change(limitedReason, { target: { value: 'x'.repeat(501) } });
    fireEvent.submit(form);
    expect(within(form).getByText('사유 501/500자')).toBeTruthy();
    fireEvent.change(limitedReason, { target: { value: '' } });
    expect(server.calls('POST', BLOCK)).toHaveLength(0);

    await user.type(
      within(form).getByLabelText('차단 사유(감사 로그에 남아요)'),
      '이용 약관 위반',
    );
    await user.click(within(form).getByRole('button', { name: '차단하기' }));

    expect(await screen.findByText('M-EBF98301을 차단했어요.')).toBeTruthy();
    expect(server.calls('POST', BLOCK)[0].body).toEqual({
      expectedRevision: 3,
      reason: '이용 약관 위반',
    });
    const [headers] = headersOf('/block');
    expect(headers.get('X-CSRF-Token')).toBe('csrf-admin');
    expect(headers.get('Idempotency-Key')).toBeTruthy();
    const history = screen.getByRole('table', { name: '차단·해제 이력' });
    expect(within(history).getByText('이용 약관 위반')).toBeTruthy();
    expect(screen.getByRole('button', { name: '차단 해제' })).toBeTruthy();
  });

  test('그 사이 다른 관리자가 상태를 바꿨으면(409) 새로 고치라고 알린다', async () => {
    server.on('GET', MEMBER, () => json(detail(member())));
    server.on('POST', BLOCK, () => apiError(409, 'REVISION_CONFLICT'));
    const { user } = open('/admin/members/M-EBF98301');
    await user.click(await screen.findByRole('button', { name: '차단' }));
    const form = screen.getByRole('form', { name: '회원 차단' });
    await user.type(
      within(form).getByLabelText('차단 사유(감사 로그에 남아요)'),
      '중복 처리',
    );
    await user.click(within(form).getByRole('button', { name: '차단하기' }));
    expect(
      await within(form).findByText(/그 사이 회원 상태가 바뀌었어요/),
    ).toBeTruthy();
  });

  test('차단 해제가 실패하면 이유를 알리고, 다시 보낼 때 같은 키를 쓴다. 이미 같은 상태면 그렇게 알린다', async () => {
    const blocked = member({ status: 'blocked' });
    server.on('GET', MEMBER, () => json(detail(blocked)));
    let attempts = 0;
    server.on('POST', UNBLOCK, () => {
      attempts += 1;
      return attempts === 1
        ? apiError(429, 'RATE_LIMITED')
        : json({ changed: false, detail: detail(blocked) });
    });
    const { user } = open('/admin/members/M-EBF98301');

    await user.click(await screen.findByRole('button', { name: '차단 해제' }));
    const form = screen.getByRole('form', { name: '회원 차단 해제' });
    await user.type(
      within(form).getByLabelText('해제 사유(감사 로그에 남아요)'),
      '소명 확인',
    );
    await user.click(
      within(form).getByRole('button', { name: '차단 해제하기' }),
    );
    expect(
      await within(form).findByText(
        '회원 차단 해제에 실패했어요. 요청이 많아요. 잠시 후 다시 시도해 주세요.',
      ),
    ).toBeTruthy();

    await user.click(
      within(form).getByRole('button', { name: '차단 해제하기' }),
    );
    expect(await screen.findByText('이미 같은 상태예요.')).toBeTruthy();
    const keys = headersOf('/unblock').map((headers) =>
      headers.get('Idempotency-Key'),
    );
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  test('없는 회원(404)은 빈 상태로 안내한다', async () => {
    server.on('GET', MEMBER, () => apiError(404, 'RESOURCE_NOT_FOUND'));
    open('/admin/members/M-UNKNOWN');

    expect(await screen.findByText('찾는 회원이 없어요.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '차단' })).toBeNull();
  });
});

describe('A-ADM-05b 관리자 감사 로그 (FS073·NFS008)', () => {
  test('최신 기록과 결과를 보여 주고, 동작·검색 조건과 커서로 이어 읽는다', async () => {
    server.on('GET', AUDIT, (request) =>
      request.query.get('cursor') === 'next-1'
        ? json({
            items: [
              audit({
                id: 2,
                actorKind: 'system',
                actorEmail: null,
                action: 'briefing.generate',
                targetType: 'briefing-round',
                targetId: 'brf-2026-10-06-morning',
              }),
            ],
            nextCursor: null,
          })
        : json({
            items: [
              audit(),
              audit({
                id: 3,
                action: 'member.block',
                targetType: 'member',
                targetId: 'M-A85C3F86',
                reason: '이용 약관 위반',
                outcome: 'denied',
              }),
              audit({
                id: 4,
                actorKind: 'anonymous',
                actorEmail: null,
                actorId: 'unknown',
                action: 'auth.login_failed',
                targetId: null,
                outcome: 'denied',
              }),
            ],
            nextCursor: 'next-1',
          }),
    );
    const { user, location } = open('/admin/audit');

    const table = await screen.findByRole('table', { name: '감사 로그' });
    expect(within(table).getByText('로그인')).toBeTruthy();
    expect(within(table).getByText('admin-session · admin-demo')).toBeTruthy();
    expect(within(table).getAllByText('거부됨')).toHaveLength(2);
    expect(within(table).getByText('이용 약관 위반')).toBeTruthy();
    expect(within(table).getByText('익명')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '더 보기' }));
    expect(await within(table).findByText('시스템')).toBeTruthy();
    expect(within(table).getByText('브리핑 생성')).toBeTruthy();

    await user.selectOptions(screen.getByLabelText('동작'), 'member.block');
    await user.type(
      screen.getByRole('searchbox', { name: '감사 로그 검색' }),
      'M-A8',
    );
    await waitFor(() => {
      const query = server.calls('GET', AUDIT).at(-1)?.query;
      expect(query?.get('action')).toBe('member.block');
      expect(query?.get('q')).toBe('M-A8');
      expect(query?.get('cursor')).toBeNull();
    });
    expect(location()).toBe('/admin/audit?action=member.block&q=M-A8');
  });

  test('조회에 실패하면 다시 시도할 수 있다', async () => {
    let attempts = 0;
    server.on('GET', AUDIT, () => {
      attempts += 1;
      return attempts === 1
        ? apiError(403, 'ACCESS_DENIED')
        : json({ items: [], nextCursor: null });
    });
    const { user } = open('/admin/audit');

    const alert = await screen.findByRole('alert');
    expect(
      within(alert).getByText(
        '이 화면을 볼 권한이 없어요. 관리자 권한을 확인해 주세요.',
      ),
    ).toBeTruthy();
    await user.click(within(alert).getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('조건에 맞는 기록이 없어요.')).toBeTruthy();
  });
});
