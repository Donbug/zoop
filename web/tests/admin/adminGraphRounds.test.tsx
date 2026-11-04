import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import AdminPipelinePage from '@/pages/admin/pipeline/AdminPipelinePage';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type {
  GraphRound,
  GraphRoundDetail,
  GraphRoundList,
} from '@/types/admin/graphRounds';
import type {
  GraphVersion,
  GraphVersionList,
} from '@/types/admin/graphVersions';
import { kstMinuteToIso } from '@/util/format';
import {
  apiError,
  deferred,
  createFakeServer,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';
import { OVERVIEW, onOverview, overview } from '../support/adminPipeline';

// A-ADM-03 회차 탭 (#55, listGraphRounds·getGraphRound·retryGraphRound·startGraphRound). 합성 fixture.

const SESSION = '/api/v1/admin/auth/session';
const ROUNDS = '/api/v1/admin/pipeline/rounds';
const ROUND = `${ROUNDS}/:roundId`;
const RETRY = `${ROUNDS}/:roundId/retry`;
const JOBS = '/api/v1/admin/jobs';
const VERSIONS = '/api/v1/admin/graph/versions';
const ACTIVATE = `${VERSIONS}/:versionId/activate`;

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

function round(overrides: Partial<GraphRound> = {}): GraphRound {
  return {
    roundId: 'round-20261103T0935',
    slotAt: '2026-11-03T00:35:00Z',
    stage: 'failed',
    startedBy: 'system:scheduler',
    attempts: 3,
    nextAttemptAt: null,
    plan: { planId: 's2plan-synthetic', planDigest: 'a'.repeat(64) },
    analysisJobId: 'job-plan-1',
    handoff: null,
    graphVersionId: null,
    activatedVersionId: null,
    activationNote: null,
    failureCode: 'freeze_timeout',
    lease: null,
    createdAt: '2026-11-03T00:35:02Z',
    updatedAt: '2026-11-03T01:10:00Z',
    ...overrides,
  };
}

const imported = round({
  roundId: 'round-20261103T1005',
  slotAt: '2026-11-03T01:05:00Z',
  stage: 'imported',
  attempts: 0,
  failureCode: null,
  handoff: {
    handoffId: 'handoff-synthetic',
    manifestDigest: 'b'.repeat(64),
    bundleDigest: 'c'.repeat(64),
  },
  graphVersionId: 'gv-synthetic',
  updatedAt: '2026-11-03T01:30:00Z',
});

function detail(row: GraphRound): GraphRoundDetail {
  return {
    round: row,
    events: [
      {
        id: 1,
        at: '2026-11-03T00:35:03Z',
        stage: 'scheduled',
        outcome: 'advanced',
        code: null,
        requestId: 'req-1',
        detail: null,
      },
      {
        id: 2,
        at: '2026-11-03T01:10:00Z',
        stage: 'freeze_requested',
        outcome: 'failed',
        code: 'freeze_timeout',
        requestId: null,
        detail: { failedAt: 'freeze_requested' },
      },
    ],
  };
}

const list = (items: GraphRound[], nextCursor: string | null = null) =>
  json({ items, nextCursor } satisfies GraphRoundList);

function open(path = '/admin/pipeline?tab=rounds') {
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
  onOverview(server);
});

describe('A-ADM-03 회차 탭 (#55)', () => {
  test('개요에 회차 실행기 상태를 보이고, 회차 탭에서 목록·상세·단계별 기록을 보여 주며 고른 회차를 주소에 남긴다', async () => {
    server.on('GET', OVERVIEW, () =>
      json(
        overview({
          rounds: {
            enabled: true,
            nextSlotAt: '2026-11-03T01:35:00Z',
            lastTickAt: '2026-11-03T01:20:00Z',
            openRounds: 1,
            recent: [],
          },
        }),
      ),
    );
    server.on('GET', ROUNDS, () => list([imported, round()]));
    server.on('GET', ROUND, ({ params }) =>
      json(detail(params.roundId === imported.roundId ? imported : round())),
    );
    server.on('GET', JOBS, () =>
      json({
        items: [],
        active: null,
        lock: { locked: false, jobId: null, reason: null },
        ingest: {
          at: null,
          jobId: null,
          outcome: null,
          newArticles: null,
          unresolvedFailures: null,
        },
        retryRule: null,
        nextCursor: null,
      }),
    );
    server.on('GET', '/api/v1/admin/jobs/:jobId', () =>
      apiError(404, 'RESOURCE_NOT_FOUND'),
    );
    const { user, location } = open('/admin/pipeline');

    expect(await screen.findByText('회차 실행기 동작 중')).toBeTruthy();
    expect(screen.getByText('진행 중 1건')).toBeTruthy();
    expect(
      screen.getByText(
        '다음 회차 2026-11-03 10:35 KST · 마지막 확인 2026-11-03 10:20 KST',
      ),
    ).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '회차 보기' }));
    expect(location()).toBe('/admin/pipeline?tab=rounds');

    const table = await screen.findByRole('table', {
      name: '그래프 회차 목록',
    });
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1]).getByText('수입 완료')).toBeTruthy();
    expect(within(rows[2]).getByText('실패')).toBeTruthy();
    expect(within(rows[2]).getByText('freeze_timeout')).toBeTruthy();
    expect(within(rows[2]).getByText('정기')).toBeTruthy();

    await user.click(
      within(rows[2]).getByRole('button', { name: 'round-20261103T0935' }),
    );
    expect(location()).toBe(
      '/admin/pipeline?tab=rounds&round=round-20261103T0935',
    );
    const aside = screen.getByRole('complementary', { name: '회차 상세' });
    expect(
      await within(aside).findByRole('heading', {
        name: /round-20261103T0935/,
      }),
    ).toBeTruthy();
    const events = within(aside).getByRole('table', { name: '회차 이벤트' });
    const eventRows = within(events).getAllByRole('row');
    expect(within(eventRows[2]).getByText('묶음 요청됨')).toBeTruthy();
    expect(within(eventRows[2]).getByText('실패')).toBeTruthy();
    expect(
      within(eventRows[2]).getByText('failedAt=freeze_requested'),
    ).toBeTruthy();
    expect(within(aside).getByRole('button', { name: '재시도' })).toBeTruthy();

    // 수입 완료 회차는 재시도하지 않고, 수입한 버전은 그래프 버전 탭으로 잇는다.
    await user.click(
      within(rows[1]).getByRole('button', { name: 'round-20261103T1005' }),
    );
    expect(
      await within(aside).findByRole('button', { name: 'gv-synthetic' }),
    ).toBeTruthy();
    expect(within(aside).queryByRole('button', { name: '재시도' })).toBeNull();

    // 분석 작업은 작업 탭의 그 작업으로 잇는다.
    await user.click(
      within(rows[2]).getByRole('button', { name: 'round-20261103T0935' }),
    );
    await user.click(
      await within(aside).findByRole('button', { name: 'job-plan-1' }),
    );
    expect(location()).toBe(
      '/admin/pipeline?tab=jobs&round=round-20261103T0935&job=job-plan-1',
    );
  });

  test('개요에 회차 항목이 없거나 실행기가 꺼져 있으면 그대로 안내한다', async () => {
    server.on('GET', OVERVIEW, () =>
      json(
        overview({
          rounds: {
            enabled: false,
            nextSlotAt: null,
            lastTickAt: null,
            openRounds: 0,
            recent: [],
          },
        }),
      ),
    );
    server.on('GET', ROUNDS, () => list([]));
    open();

    expect(
      await screen.findByText('회차 실행기 꺼짐 또는 확인 불가'),
    ).toBeTruthy();
    expect(screen.queryByText(/다음 회차/)).toBeNull();
    expect(await screen.findByText('아직 그래프 회차가 없어요.')).toBeTruthy();
  });

  test('단계를 고르면 그 단계로 다시 조회하고, 더 보기는 커서를 보낸다', async () => {
    server.on('GET', ROUNDS, ({ query }) => {
      if (query.get('cursor') === 'c2') return list([round()]);
      if (query.get('stage') === 'failed') return list([round()]);
      return list([imported], 'c2');
    });
    const { user, location } = open();

    await user.click(await screen.findByRole('button', { name: '더 보기' }));
    expect(
      await screen.findByRole('button', { name: 'round-20261103T0935' }),
    ).toBeTruthy();
    expect(server.calls('GET', ROUNDS).at(-1)?.query.get('cursor')).toBe('c2');

    await user.selectOptions(screen.getByLabelText('단계'), 'failed');
    expect(location()).toBe('/admin/pipeline?tab=rounds&roundStage=failed');
    expect(
      await screen.findByRole('button', { name: 'round-20261103T0935' }),
    ).toBeTruthy();
    expect(
      screen.queryByRole('button', { name: 'round-20261103T1005' }),
    ).toBeNull();
    expect(server.calls('GET', ROUNDS).at(-1)?.query.get('stage')).toBe(
      'failed',
    );
  });

  test('재시도는 본문 없이 Idempotency-Key와 함께 보내고, 상세와 목록을 다시 읽는다', async () => {
    let retried = false;
    const reopened = round({
      stage: 'analysis_done',
      failureCode: null,
      attempts: 0,
    });
    server.on('GET', ROUNDS, () => list([retried ? reopened : round()]));
    server.on('GET', ROUND, () => json(detail(retried ? reopened : round())));
    server.on('POST', RETRY, () => {
      retried = true;
      return json(reopened, 202);
    });
    const { user } = open(
      '/admin/pipeline?tab=rounds&round=round-20261103T0935',
    );

    const aside = await screen.findByRole('complementary', {
      name: '회차 상세',
    });
    await user.click(
      await within(aside).findByRole('button', { name: '재시도' }),
    );
    const form = within(aside).getByRole('form', { name: '회차 재시도' });
    await user.click(within(form).getByRole('button', { name: '재시도하기' }));

    expect(
      await screen.findByText(
        'round-20261103T0935 회차를 분석 완료 단계부터 다시 열었어요. 회차 실행기의 다음 바퀴가 진행해요.',
      ),
    ).toBeTruthy();
    const [call] = server.calls('POST', RETRY);
    expect(call.params.roundId).toBe('round-20261103T0935');
    expect(call.body).toBeUndefined();
    expect(call.headers.get('Idempotency-Key')).toBeTruthy();
    expect(call.headers.get('X-CSRF-Token')).toBe('csrf-admin');
    // 목록을 다시 읽는 동안 탭 전체가 다시 그려지므로 상세를 다시 찾는다.
    const reloaded = await screen.findByRole('complementary', {
      name: '회차 상세',
    });
    expect(await within(reloaded).findByText('분석 완료')).toBeTruthy();
    expect(
      within(reloaded).queryByRole('button', { name: '재시도' }),
    ).toBeNull();
  });

  test('AI가 실패로 답한 회차는 재시도해도 같은 결과라고 알리고, 503은 같은 키로 다시 보내며 404는 실행기 안내 뒤 새 키를 쓴다', async () => {
    const aiFailed = round({ failureCode: 'run_failed:source_unavailable' });
    server.on('GET', ROUNDS, () => list([aiFailed]));
    server.on('GET', ROUND, () => json(detail(aiFailed)));
    server.on('POST', RETRY, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = open(
      '/admin/pipeline?tab=rounds&round=round-20261103T0935',
    );

    const aside = await screen.findByRole('complementary', {
      name: '회차 상세',
    });
    await user.click(
      await within(aside).findByRole('button', { name: '재시도' }),
    );
    const form = within(aside).getByRole('form', { name: '회차 재시도' });
    expect(within(form).getByText(/AI가 실패로 답한 회차예요/)).toBeTruthy();

    await user.click(within(form).getByRole('button', { name: '재시도하기' }));
    expect(
      await within(form).findByText(/회차 실행기 상태를 확인하지 못했어요/),
    ).toBeTruthy();
    server.on('POST', RETRY, () => apiError(404, 'RESOURCE_NOT_FOUND'));
    await user.click(within(form).getByRole('button', { name: '재시도하기' }));
    expect(
      await within(form).findByText(/회차 실행기가 동작하지 않거나/),
    ).toBeTruthy();
    // 404는 확정 거절이라 다음 요청은 새 키를 쓴다.
    await user.click(within(form).getByRole('button', { name: '재시도하기' }));
    await waitFor(() => expect(server.calls('POST', RETRY)).toHaveLength(3));
    const calls = server.calls('POST', RETRY);
    expect(calls[2].headers.get('Idempotency-Key')).not.toBe(
      calls[1].headers.get('Idempotency-Key'),
    );
    // 503은 응답을 확정하지 못한 것이라 같은 키로 다시 보낸다.
    expect(calls[1].headers.get('Idempotency-Key')).toBe(
      calls[0].headers.get('Idempotency-Key'),
    );
  });

  test('회차 시작은 지금(slotAt null) 또는 KST로 지정한 분을 UTC로 보내고, 같은 시각이 있으면 409를 안내한다', async () => {
    const started = round({
      roundId: 'round-20261103T0905',
      slotAt: '2026-11-03T00:05:00Z',
      stage: 'scheduled',
      startedBy: 'admin:adm-1',
      failureCode: null,
    });
    server.on('GET', ROUNDS, () => list([]));
    server.on('GET', ROUND, () => json(detail(started)));
    server.on('POST', ROUNDS, ({ body }) =>
      (body as { slotAt: string | null }).slotAt === null
        ? apiError(409, 'REVISION_CONFLICT')
        : json(started, 202),
    );
    const { user, location } = open();

    await user.click(await screen.findByRole('button', { name: '회차 시작' }));
    let form = screen.getByRole('form', { name: '회차 시작' });
    await user.click(
      within(form).getByRole('button', { name: '회차 시작하기' }),
    );
    expect(
      await within(form).findByText(/같은 시각의 회차가 이미 있어요/),
    ).toBeTruthy();
    expect(server.calls('POST', ROUNDS)[0].body).toEqual({ slotAt: null });

    form = screen.getByRole('form', { name: '회차 시작' });
    await user.click(within(form).getByLabelText('시각 지정(KST)'));
    await user.click(
      within(form).getByRole('button', { name: '회차 시작하기' }),
    );
    expect(
      within(form).getByText('회차 시각을 분 단위로 입력해 주세요.'),
    ).toBeTruthy();
    expect(server.calls('POST', ROUNDS)).toHaveLength(1);

    await user.type(
      within(form).getByLabelText('회차 시각(KST, 분 단위)'),
      '2026-11-03T09:05',
    );
    await user.click(
      within(form).getByRole('button', { name: '회차 시작하기' }),
    );
    expect(
      await screen.findByText(
        'round-20261103T0905 회차를 만들었어요. 회차 실행기의 다음 바퀴가 진행해요.',
      ),
    ).toBeTruthy();
    const calls = server.calls('POST', ROUNDS);
    expect(calls[1].body).toEqual({ slotAt: '2026-11-03T00:05:00Z' });
    expect(calls[1].headers.get('Idempotency-Key')).not.toBe(
      calls[0].headers.get('Idempotency-Key'),
    );
    expect(location()).toBe(
      '/admin/pipeline?tab=rounds&round=round-20261103T0905',
    );
  });

  test('KST 회차 시각은 분 단위 UTC로 바꾸고, 없는 날짜·시각은 보내지 않는다', () => {
    expect(kstMinuteToIso('2026-11-03T09:05')).toBe('2026-11-03T00:05:00Z');
    expect(kstMinuteToIso('2026-11-04T08:30')).toBe('2026-11-03T23:30:00Z');
    expect(kstMinuteToIso('2026-02-31T10:00')).toBeNull();
    expect(kstMinuteToIso('2026-11-04T24:00')).toBeNull();
    expect(kstMinuteToIso('2026-11-04T09:05:30')).toBeNull();
    expect(kstMinuteToIso('')).toBeNull();
  });

  test('버전 탭을 먼저 연 뒤 회차 상세의 수입한 버전을 누르면 버전 목록을 다시 읽어 새 버전을 보여 준다', async () => {
    let importedNow = false;
    const synthetic: GraphVersion = {
      id: 'gv-synthetic',
      sequence: 1,
      kind: 'snapshot',
      createdAt: '2026-11-03T01:30:00Z',
      createdBy: 'importer',
      reason: '합성 회차 수입',
      sourceLabel: '합성 handoff',
      policyVersion: null,
      issueCount: 1,
      relationCount: 1,
      articleCount: 1,
      candidateCount: null,
      sha256: 'd'.repeat(64),
      bytes: 1,
      active: false,
      activatedAt: null,
      graphDb: { status: 'pending', pendingJobsAtCreation: 0, note: null },
    };
    server.on('GET', OVERVIEW, () => json(overview()));
    server.on('GET', VERSIONS, () =>
      json({
        activeVersionId: null,
        items: importedNow ? [synthetic] : [],
        activations: [],
        nextCursor: null,
      } satisfies GraphVersionList),
    );
    server.on('GET', ROUNDS, () => list([imported]));
    server.on('GET', ROUND, () => json(detail(imported)));
    const { user } = open('/admin/pipeline?tab=versions');
    await waitFor(() => expect(server.calls('GET', VERSIONS)).toHaveLength(1));

    importedNow = true;
    await user.click(screen.getByRole('tab', { name: '회차' }));
    const table = await screen.findByRole('table', {
      name: '그래프 회차 목록',
    });
    await user.click(
      within(table).getByRole('button', { name: 'round-20261103T1005' }),
    );
    const aside = screen.getByRole('complementary', { name: '회차 상세' });
    await user.click(
      await within(aside).findByRole('button', { name: 'gv-synthetic' }),
    );

    expect(
      await screen.findByRole('button', { name: 'gv-synthetic로 전환' }),
    ).toBeTruthy();
    expect(server.calls('GET', VERSIONS)).toHaveLength(2);
  });

  test('버전 탭의 더 보기가 끝나기 전에 회차의 수입한 버전을 누르면 더 보기가 끝난 뒤 버전 목록을 다시 읽는다', async () => {
    let importedNow = false;
    const version = (id: string, sequence: number): GraphVersion => ({
      id,
      sequence,
      kind: 'snapshot',
      createdAt: '2026-11-03T01:30:00Z',
      createdBy: 'importer',
      reason: '합성 회차 수입',
      sourceLabel: '합성 handoff',
      policyVersion: null,
      issueCount: 1,
      relationCount: 1,
      articleCount: 1,
      candidateCount: null,
      sha256: 'd'.repeat(64),
      bytes: 1,
      active: false,
      activatedAt: null,
      graphDb: { status: 'pending', pendingJobsAtCreation: 0, note: null },
    });
    const more = deferred<Response>();
    let moreReads = 0;
    const page = (items: GraphVersion[], nextCursor: string | null) =>
      json({
        activeVersionId: null,
        items,
        activations: [],
        nextCursor,
      } satisfies GraphVersionList);
    server.on('GET', OVERVIEW, () => json(overview()));
    server.on('GET', VERSIONS, ({ query }) => {
      if (query.get('cursor')) {
        moreReads += 1;
        return moreReads === 1
          ? more.promise
          : page([version('gv-older', 1)], null);
      }
      return page(
        importedNow
          ? [version('gv-synthetic', 3), version('gv-old', 2)]
          : [version('gv-old', 2)],
        'c1',
      );
    });
    server.on('GET', ROUNDS, () => list([imported]));
    server.on('GET', ROUND, () => json(detail(imported)));
    const { user } = open('/admin/pipeline?tab=versions');
    await user.click(await screen.findByRole('button', { name: '더 보기' }));

    importedNow = true;
    await user.click(screen.getByRole('tab', { name: '회차' }));
    const table = await screen.findByRole('table', {
      name: '그래프 회차 목록',
    });
    await user.click(
      within(table).getByRole('button', { name: 'round-20261103T1005' }),
    );
    const aside = screen.getByRole('complementary', { name: '회차 상세' });
    await user.click(
      await within(aside).findByRole('button', { name: 'gv-synthetic' }),
    );
    const firstPageReads = () =>
      server.calls('GET', VERSIONS).filter(({ query }) => !query.get('cursor'))
        .length;
    expect(firstPageReads()).toBe(1);

    more.resolve(page([version('gv-older', 1)], null));
    expect(
      await screen.findByRole('button', { name: 'gv-synthetic로 전환' }),
    ).toBeTruthy();
    expect(firstPageReads()).toBe(2);
  });
  test('버전 전환 요청 중에 회차의 수입한 버전을 누르고 전환이 실패해도 버전 목록을 다시 읽는다', async () => {
    let importedNow = false;
    const version = (id: string, sequence: number): GraphVersion => ({
      id,
      sequence,
      kind: 'snapshot',
      createdAt: '2026-11-03T01:30:00Z',
      createdBy: 'importer',
      reason: '합성 회차 수입',
      sourceLabel: '합성 handoff',
      policyVersion: null,
      issueCount: 1,
      relationCount: 1,
      articleCount: 1,
      candidateCount: null,
      sha256: 'd'.repeat(64),
      bytes: 1,
      active: false,
      activatedAt: null,
      graphDb: { status: 'pending', pendingJobsAtCreation: 0, note: null },
    });
    const activation = deferred<Response>();
    server.on('GET', OVERVIEW, () => json(overview()));
    server.on('GET', VERSIONS, () =>
      json({
        activeVersionId: null,
        items: importedNow
          ? [version('gv-synthetic', 2), version('gv-old', 1)]
          : [version('gv-old', 1)],
        activations: [],
        nextCursor: null,
      } satisfies GraphVersionList),
    );
    server.on('POST', ACTIVATE, () => activation.promise);
    server.on('GET', ROUNDS, () => list([imported]));
    server.on('GET', ROUND, () => json(detail(imported)));
    const { user } = open('/admin/pipeline?tab=versions');
    await user.click(
      await screen.findByRole('button', { name: 'gv-old로 전환' }),
    );
    const form = screen.getByRole('form', { name: '그래프 버전 전환' });
    await user.type(
      within(form).getByLabelText('전환 사유(감사 로그에 남아요)'),
      '합성 전환',
    );
    await user.click(
      within(form).getByRole('button', { name: 'gv-old로 전환' }),
    );
    await waitFor(() => expect(server.calls('POST', ACTIVATE)).toHaveLength(1));

    importedNow = true;
    await user.click(screen.getByRole('tab', { name: '회차' }));
    const table = await screen.findByRole('table', {
      name: '그래프 회차 목록',
    });
    await user.click(
      within(table).getByRole('button', { name: 'round-20261103T1005' }),
    );
    const aside = screen.getByRole('complementary', { name: '회차 상세' });
    await user.click(
      await within(aside).findByRole('button', { name: 'gv-synthetic' }),
    );
    expect(server.calls('GET', VERSIONS)).toHaveLength(1);

    activation.resolve(apiError(409, 'REVISION_CONFLICT'));
    expect(
      await screen.findByRole('button', { name: 'gv-synthetic로 전환' }),
    ).toBeTruthy();
    expect(server.calls('GET', VERSIONS)).toHaveLength(2);
  });
  test('버전 목록을 다시 읽는 중에 다른 회차의 수입한 버전을 누르면 그 읽기가 끝난 뒤 한 번 더 읽는다', async () => {
    const later = round({
      ...imported,
      roundId: 'round-20261103T1035',
      slotAt: '2026-11-03T01:35:00Z',
      graphVersionId: 'gv-synthetic-2',
    });
    const version = (id: string, sequence: number): GraphVersion => ({
      id,
      sequence,
      kind: 'snapshot',
      createdAt: '2026-11-03T01:30:00Z',
      createdBy: 'importer',
      reason: '합성 회차 수입',
      sourceLabel: '합성 handoff',
      policyVersion: null,
      issueCount: 1,
      relationCount: 1,
      articleCount: 1,
      candidateCount: null,
      sha256: 'd'.repeat(64),
      bytes: 1,
      active: false,
      activatedAt: null,
      graphDb: { status: 'pending', pendingJobsAtCreation: 0, note: null },
    });
    const page = (items: GraphVersion[]) =>
      json({
        activeVersionId: null,
        items,
        activations: [],
        nextCursor: null,
      } satisfies GraphVersionList);
    const refreshing = deferred<Response>();
    let reads = 0;
    server.on('GET', OVERVIEW, () => json(overview()));
    server.on('GET', VERSIONS, () => {
      reads += 1;
      if (reads === 1) return page([version('gv-old', 1)]);
      if (reads === 2) return refreshing.promise;
      return page([
        version('gv-synthetic-2', 3),
        version('gv-synthetic', 2),
        version('gv-old', 1),
      ]);
    });
    server.on('GET', ROUNDS, () => list([later, imported]));
    server.on('GET', ROUND, ({ params }) =>
      json(detail(params.roundId === later.roundId ? later : imported)),
    );
    const { user } = open('/admin/pipeline?tab=versions');
    await waitFor(() => expect(server.calls('GET', VERSIONS)).toHaveLength(1));

    const openVersionFrom = async (roundId: string, versionId: string) => {
      await user.click(screen.getByRole('tab', { name: '회차' }));
      const table = await screen.findByRole('table', {
        name: '그래프 회차 목록',
      });
      await user.click(within(table).getByRole('button', { name: roundId }));
      const aside = screen.getByRole('complementary', { name: '회차 상세' });
      await user.click(
        await within(aside).findByRole('button', { name: versionId }),
      );
    };
    await openVersionFrom(imported.roundId, 'gv-synthetic');
    await waitFor(() => expect(server.calls('GET', VERSIONS)).toHaveLength(2));
    await openVersionFrom(later.roundId, 'gv-synthetic-2');
    expect(server.calls('GET', VERSIONS)).toHaveLength(2);

    refreshing.resolve(
      page([version('gv-synthetic', 2), version('gv-old', 1)]),
    );
    expect(
      await screen.findByRole('button', { name: 'gv-synthetic-2로 전환' }),
    ).toBeTruthy();
    expect(server.calls('GET', VERSIONS)).toHaveLength(3);
  });
});
