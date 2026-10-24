import { act, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import AdminPipelinePage from '@/pages/admin/pipeline/AdminPipelinePage';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type {
  GraphVersion,
  GraphVersionList,
} from '@/types/admin/graphVersions';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

// A-ADM-03 그래프 버전 탭 (FS059, listGraphVersions·activateGraphVersion). 합성 fixture.

const SESSION = '/api/v1/admin/auth/session';
const VERSIONS = '/api/v1/admin/graph/versions';
const ACTIVATE = '/api/v1/admin/graph/versions/:versionId/activate';

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

function version(overrides: Partial<GraphVersion> = {}): GraphVersion {
  return {
    id: 'v2',
    sequence: 2,
    kind: 'snapshot',
    createdAt: '2026-10-21T03:00:00Z',
    createdBy: 'importer',
    reason: '정기 게시',
    sourceLabel: '원장 2026-10-21',
    policyVersion: 'R1@2',
    issueCount: 95,
    relationCount: 190,
    articleCount: 39,
    candidateCount: 407,
    sha256: 'a'.repeat(64),
    bytes: 1024,
    active: true,
    activatedAt: '2026-10-21T03:05:00Z',
    graphDb: { status: 'reflected', pendingJobsAtCreation: 0, note: null },
    ...overrides,
  };
}

function list(active: 'v1' | 'v2' = 'v2'): GraphVersionList {
  return {
    activeVersionId: active,
    items: [
      version({ active: active === 'v2' }),
      version({
        id: 'v1',
        sequence: 1,
        kind: 'fixture',
        reason: null,
        sourceLabel: '합성 fixture',
        issueCount: 12,
        relationCount: 20,
        articleCount: 8,
        active: active === 'v1',
        graphDb: { status: 'pending', pendingJobsAtCreation: 3, note: null },
      }),
    ],
    activations: [
      {
        versionId: 'v2',
        previousVersionId: 'v1',
        at: '2026-10-21T03:05:00Z',
        adminEmail: 'admin@zoop.test',
        reason: '정기 게시',
        action: 'activate',
      },
    ],
    nextCursor: null,
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

function open(path = '/admin/pipeline') {
  return renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [{ path: '/admin/pipeline', element: <AdminPipelinePage /> }],
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

describe('A-ADM-03 그래프 버전 (FS059)', () => {
  test('표시 중인 버전·버전 목록·전환 이력을 보여 주고, 표시 중인 버전에는 전환 버튼이 없다', async () => {
    server.on('GET', VERSIONS, () => json(list()));
    open();

    const table = await screen.findByRole('table', {
      name: '그래프 버전 목록',
    });
    expect(screen.getByRole('tab', { name: '그래프 버전' })).toBeTruthy();
    expect(
      screen
        .getByRole('tab', { name: '그래프 버전' })
        .getAttribute('aria-selected'),
    ).toBe('true');
    const [, v2, v1] = within(table).getAllByRole('row');
    expect(within(v2).getByText('표시 중')).toBeTruthy();
    expect(within(v2).getByText('반영됨')).toBeTruthy();
    expect(within(v2).queryByRole('button')).toBeNull();
    expect(within(v1).getByText('합성')).toBeTruthy();
    expect(within(v1).getByText('반영 대기')).toBeTruthy();
    expect(within(v1).getByRole('button', { name: 'v1로 전환' })).toBeTruthy();

    const history = screen.getByRole('table', {
      name: '그래프 버전 전환 이력',
    });
    expect(within(history).getByText('v1 → v2')).toBeTruthy();
    expect(within(history).getByText('전환')).toBeTruthy();
  });

  test('사유를 받아 화면에서 본 표시 버전과 함께 전환을 보내고, 성공하면 목록을 다시 읽는다', async () => {
    let active: 'v1' | 'v2' = 'v2';
    server.on('GET', VERSIONS, () => json(list(active)));
    server.on('POST', ACTIVATE, () => {
      active = 'v1';
      return json({
        activeVersionId: 'v1',
        previousActiveVersionId: 'v2',
        idempotent: false,
      });
    });
    const { user } = open();

    await user.click(await screen.findByRole('button', { name: 'v1로 전환' }));
    const form = screen.getByRole('form', { name: '그래프 버전 전환' });
    await user.click(within(form).getByRole('button', { name: 'v1로 전환' }));
    expect(within(form).getByText('사유를 입력해 주세요.')).toBeTruthy();
    expect(server.calls('POST', ACTIVATE)).toHaveLength(0);

    await user.type(
      within(form).getByLabelText('전환 사유(감사 로그에 남아요)'),
      '이전 버전으로 되돌림',
    );
    await user.click(within(form).getByRole('button', { name: 'v1로 전환' }));

    expect(await screen.findByText('v1로 바꿨어요.')).toBeTruthy();
    const [call] = server.calls('POST', ACTIVATE);
    expect(call.params.versionId).toBe('v1');
    expect(call.body).toEqual({
      reason: '이전 버전으로 되돌림',
      expectedActiveVersionId: 'v2',
    });
    const [headers] = headersOf('/activate');
    expect(headers.get('X-CSRF-Token')).toBe('csrf-admin');
    expect(headers.get('Idempotency-Key')).toBeTruthy();
    expect(server.calls('GET', VERSIONS).length).toBeGreaterThan(1);
    const table = await screen.findByRole('table', {
      name: '그래프 버전 목록',
    });
    const [, v2, v1] = within(table).getAllByRole('row');
    expect(await within(v1).findByText('표시 중')).toBeTruthy();
    expect(within(v2).getByRole('button', { name: 'v2로 전환' })).toBeTruthy();
  });

  test('그 사이 다른 관리자가 바꿨으면(409) 새로 고치라고 알린다', async () => {
    server.on('GET', VERSIONS, () => json(list()));
    server.on('POST', ACTIVATE, () => apiError(409, 'REVISION_CONFLICT'));
    const { user } = open();

    await user.click(await screen.findByRole('button', { name: 'v1로 전환' }));
    const form = screen.getByRole('form', { name: '그래프 버전 전환' });
    await user.type(
      within(form).getByLabelText('전환 사유(감사 로그에 남아요)'),
      '되돌림',
    );
    await user.click(within(form).getByRole('button', { name: 'v1로 전환' }));

    expect(
      await within(form).findByText(
        /표시 버전이나 근거 공개 조건이 달라져 전환하지 못했어요/,
      ),
    ).toBeTruthy();
  });

  test('요청한 버전과 다른 성공 응답은 전환 완료로 표시하지 않는다', async () => {
    server.on('GET', VERSIONS, () => json(list()));
    server.on('POST', ACTIVATE, () =>
      json({
        activeVersionId: 'v0',
        previousActiveVersionId: 'v2',
        idempotent: false,
      }),
    );
    const { user } = open();

    await user.click(await screen.findByRole('button', { name: 'v1로 전환' }));
    const form = screen.getByRole('form', { name: '그래프 버전 전환' });
    await user.type(
      within(form).getByLabelText('전환 사유(감사 로그에 남아요)'),
      '되돌림',
    );
    await user.click(within(form).getByRole('button', { name: 'v1로 전환' }));

    expect(
      await within(form).findByText(
        '버전을 바꾸지 못했어요. 잠시 후 다시 시도해 주세요.',
      ),
    ).toBeTruthy();
    expect(screen.queryByText('v0로 바꿨어요.')).toBeNull();
    expect(server.calls('GET', VERSIONS)).toHaveLength(1);
  });

  test('목록을 불러오지 못하면 다시 시도할 수 있고, 후보·작업 탭은 준비 중으로 보인다', async () => {
    server.on('GET', VERSIONS, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user, location } = open();

    expect(
      await screen.findByText('그래프 버전을 불러오지 못했어요'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: '후보' }));
    expect(location()).toBe('/admin/pipeline?tab=candidates');
    expect(screen.getByText(/후보 검수는 아직 준비 중이에요/)).toBeTruthy();
    await user.click(screen.getByRole('tab', { name: '작업' }));
    expect(
      screen.getByText(/분석 작업 관리는 아직 준비 중이에요/),
    ).toBeTruthy();
  });

  test('전환 요청이 진행 중이면 다른 버전을 고를 수 없고, 탭을 옮겨도 결과를 잃지 않는다', async () => {
    const base = list();
    const three: GraphVersionList = {
      ...base,
      items: [
        ...base.items,
        version({ id: 'v0', sequence: 0, active: false, reason: null }),
      ],
    };
    server.on('GET', VERSIONS, () => json(three));
    const pending = deferred<Response>();
    server.on('POST', ACTIVATE, () => pending.promise);
    const { user } = open();

    await user.click(await screen.findByRole('button', { name: 'v1로 전환' }));
    const form = screen.getByRole('form', { name: '그래프 버전 전환' });
    await user.type(
      within(form).getByLabelText('전환 사유(감사 로그에 남아요)'),
      '되돌림',
    );
    await user.click(within(form).getByRole('button', { name: 'v1로 전환' }));
    expect(
      (screen.getByRole('button', { name: 'v0로 전환' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    await user.click(screen.getByRole('tab', { name: '후보' }));
    await act(async () =>
      pending.resolve(
        json({
          activeVersionId: 'v1',
          previousActiveVersionId: 'v2',
          idempotent: false,
        }),
      ),
    );
    await user.click(screen.getByRole('tab', { name: '그래프 버전' }));
    expect(await screen.findByText('v1로 바꿨어요.')).toBeTruthy();
    expect(server.calls('POST', ACTIVATE)).toHaveLength(1);
  });

  test('더 불러온 쪽의 표시 버전이 첫 쪽과 다르면 전환을 막고 다시 불러오게 한다', async () => {
    server.on('GET', VERSIONS, ({ query }) =>
      query.get('cursor')
        ? json({
            ...list('v1'),
            items: [version({ id: 'v0', sequence: 0, active: false })],
            nextCursor: null,
          })
        : json({
            ...list('v2'),
            items: [list('v2').items[0]],
            nextCursor: 'c1',
          }),
    );
    const { user } = open();

    await user.click(await screen.findByRole('button', { name: '더 보기' }));
    expect(
      await screen.findByText(/목록을 읽는 사이 표시 버전이 바뀌었어요/),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: /로 전환$/ })).toBeNull();
    const reads = server.calls('GET', VERSIONS).length;
    await user.click(screen.getByRole('button', { name: '다시 불러오기' }));
    await screen.findByRole('button', { name: '더 보기' });
    expect(server.calls('GET', VERSIONS).length).toBeGreaterThan(reads);
  });

  test('다른 탭에 있는 동안 전환이 실패해도 돌아오면 실패 안내가 남아 있다', async () => {
    server.on('GET', VERSIONS, () => json(list()));
    const pending = deferred<Response>();
    server.on('POST', ACTIVATE, () => pending.promise);
    const { user } = open();

    await user.click(await screen.findByRole('button', { name: 'v1로 전환' }));
    const form = screen.getByRole('form', { name: '그래프 버전 전환' });
    await user.type(
      within(form).getByLabelText('전환 사유(감사 로그에 남아요)'),
      '되돌림',
    );
    await user.click(within(form).getByRole('button', { name: 'v1로 전환' }));
    await user.click(screen.getByRole('tab', { name: '작업' }));
    await act(async () => pending.resolve(apiError(409, 'REVISION_CONFLICT')));
    await user.click(screen.getByRole('tab', { name: '그래프 버전' }));

    expect(
      await within(
        screen.getByRole('form', { name: '그래프 버전 전환' }),
      ).findByText(/표시 버전이나 근거 공개 조건이 달라져 전환하지 못했어요/),
    ).toBeTruthy();
    // 실패 뒤에는 진행 상태가 풀려 같은 폼에서 다시 보낼 수 있다.
    expect(
      (
        within(
          screen.getByRole('form', { name: '그래프 버전 전환' }),
        ).getByRole('button', { name: 'v1로 전환' }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  test('사유를 입력한 폼이 열린 채 페이지 간 표시 버전이 달라지면 제출을 막고 기대 버전을 바꾸지 않는다', async () => {
    server.on('GET', VERSIONS, ({ query }) =>
      query.get('cursor')
        ? json({
            ...list('v1'),
            items: [version({ id: 'v0', sequence: 0, active: false })],
            nextCursor: null,
          })
        : json({
            ...list('v2'),
            items: list('v2').items,
            nextCursor: 'c1',
          }),
    );
    server.on('POST', ACTIVATE, () =>
      json({
        activeVersionId: 'v1',
        previousActiveVersionId: 'v2',
        idempotent: false,
      }),
    );
    const { user } = open();

    await user.click(await screen.findByRole('button', { name: 'v1로 전환' }));
    const form = screen.getByRole('form', { name: '그래프 버전 전환' });
    await user.type(
      within(form).getByLabelText('전환 사유(감사 로그에 남아요)'),
      '되돌림',
    );
    await user.click(screen.getByRole('button', { name: '더 보기' }));
    expect(
      await within(form).findByText('목록을 다시 불러온 뒤 전환해 주세요.'),
    ).toBeTruthy();
    expect(within(form).getByText('v2')).toBeTruthy();
    const submit = within(form).getByRole('button', {
      name: 'v1로 전환',
    }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    await user.click(submit);
    expect(server.calls('POST', ACTIVATE)).toHaveLength(0);
  });
});
