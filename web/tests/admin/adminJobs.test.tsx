import { act, cleanup, screen, within } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import AdminPipelinePage from '@/pages/admin/pipeline/AdminPipelinePage';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type {
  AnalysisJob,
  AnalyzePlanJob,
  LegacyAnalysisJob,
  JobList,
} from '@/types/admin/jobs';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';
import { onOverview } from '../support/adminPipeline';

// A-ADM-03 작업 탭 (FS058·FS067-01·FS067-03, listAnalysisJobs·getAnalysisJob·retryAnalysisJob·cancelAnalysisJob). 합성 fixture.

const SESSION = '/api/v1/admin/auth/session';
const JOBS = '/api/v1/admin/jobs';
const JOB = '/api/v1/admin/jobs/:jobId';
const RETRY = '/api/v1/admin/jobs/:jobId/retry';
const CANCEL = '/api/v1/admin/jobs/:jobId/cancel';

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

function job(overrides: Partial<LegacyAnalysisJob> = {}): LegacyAnalysisJob {
  return {
    id: 'job-failed',
    kind: 'revalidate',
    label: 'revalidate',
    status: 'failed',
    reason: '정기 재검증',
    requestedBy: 'admin@zoop.test',
    requestedAt: '2026-10-23T01:00:00Z',
    startedAt: '2026-10-23T01:00:05Z',
    finishedAt: '2026-10-23T01:03:10Z',
    durationSeconds: 185,
    retryOf: null,
    cancelRequested: false,
    recovered: false,
    retry: { allowed: true, code: 'allowed', reason: '', blockedBy: null },
    ingest: null,
    report: {
      runId: 'run-1',
      processed: 40,
      skipped: 2,
      approved: 30,
      held: 5,
      rejected: 3,
      pending: 0,
      errorCount: 2,
      errors: [{ stage: 'verify', type: 'timeout', message: '모델 응답 지연' }],
      collectionErrorCount: 0,
      collectionErrors: [],
      elapsedSeconds: 185,
      executionMode: 'live',
      usage: {
        calls: 42,
        replayCalls: 0,
        inputTokens: 120000,
        outputTokens: 8000,
        elapsedSeconds: 180,
        estimatedCost: null,
      },
    },
    flush: null,
    error: {
      code: 'MODEL_TIMEOUT',
      message: '모델 호출이 시간 안에 끝나지 않았어요.',
    },
    ledgerBefore: null,
    ledgerAfter: null,
    ...overrides,
  };
}

const running = job({
  id: 'job-running',
  kind: 'ingest',
  label: 'ingest',
  status: 'running',
  reason: '아침 수집',
  requestedAt: '2026-10-23T02:00:00Z',
  finishedAt: null,
  durationSeconds: null,
  retry: {
    allowed: false,
    code: 'in_progress',
    reason: '대기·실행 중인 작업이에요.',
    blockedBy: null,
  },
  ingest: {
    outcome: null,
    newArticles: null,
    duplicateArticles: null,
    baselineBefore: '2026-10-22T21:00:00Z',
    baselineAfter: null,
    baselineAdvanced: false,
  },
  report: null,
  error: null,
});

const planRef = {
  planId: `s2plan-${'a'.repeat(64)}`,
  planDigest: 'b'.repeat(64),
};
function planJob(overrides: Partial<AnalyzePlanJob> = {}): AnalyzePlanJob {
  return {
    ...job(),
    kind: 'analyze_plan',
    id: 'job-plan',
    status: 'queued',
    startedAt: null,
    finishedAt: null,
    durationSeconds: null,
    ingest: null,
    report: null,
    flush: null,
    ledgerBefore: null,
    ledgerAfter: null,
    error: null,
    retry: { allowed: false, code: 'in_progress', reason: '', blockedBy: null },
    planRun: {
      ...planRef,
      admissionId: null,
      manifestDigest: null,
      sourceId: null,
      roundId: null,
      phase: 'awaiting_admission',
      totalUnits: null,
      readyUnits: 0,
      activeUnit: null,
      completion: 'ai_processing_handoff',
      publicChanged: false,
    },
    ...overrides,
  };
}

function list(items: AnalysisJob[] = [running, job()]): JobList {
  const active = items.find((item) => item.status === 'running') ?? null;
  return {
    items,
    active,
    lock: {
      locked: active !== null,
      jobId: active?.id ?? null,
      reason: active ? '다른 관리자 작업이 실행 중이에요.' : null,
    },
    ingest: {
      at: '2026-10-22T21:00:00Z',
      jobId: 'job-ingest-old',
      outcome: 'empty',
      newArticles: 0,
      unresolvedFailures: 1,
    },
    retryRule: '실패하거나 취소된 작업만 다시 실행할 수 있어요.',
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

function open(path = '/admin/pipeline?tab=jobs') {
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

describe('A-ADM-03 작업 탭 (FS058·FS067)', () => {
  test('작업 목록·진행 중인 작업·기사 처리 기준 시점을 보여 주고, 고른 작업을 주소에 남긴다', async () => {
    server.on('GET', JOBS, () => json(list()));
    server.on('GET', JOB, ({ params }) =>
      json(params.jobId === 'job-running' ? running : job()),
    );
    const { user, location } = open();

    const table = await screen.findByRole('table', { name: '작업 목록' });
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1]).getByText('신규 기사 처리')).toBeTruthy();
    expect(within(rows[1]).getByText('실행 중')).toBeTruthy();
    expect(within(rows[2]).getByText('후보 재검증')).toBeTruthy();
    expect(within(rows[2]).getByText('실패')).toBeTruthy();
    expect(within(rows[2]).getByText('3분 5초')).toBeTruthy();
    expect(
      screen.getByText('진행 중인 작업: 신규 기사 처리 · 실행 중'),
    ).toBeTruthy();
    expect(screen.getByText('다른 관리자 작업이 실행 중이에요.')).toBeTruthy();
    expect(screen.getByText(/새 기사 없음/)).toBeTruthy();
    expect(screen.getByText('1건')).toBeTruthy();

    await user.click(
      within(rows[2]).getByRole('button', { name: '후보 재검증' }),
    );
    expect(location()).toBe('/admin/pipeline?tab=jobs&job=job-failed');
    const detail = screen.getByRole('complementary', { name: '작업 상세' });
    expect(
      await within(detail).findByRole('heading', { name: /후보 재검증/ }),
    ).toBeTruthy();
    expect(
      within(detail).getByText('모델 호출이 시간 안에 끝나지 않았어요.'),
    ).toBeTruthy();
    expect(
      within(detail).getByText('verify · timeout · 모델 응답 지연'),
    ).toBeTruthy();
    expect(within(detail).getByText('42회')).toBeTruthy();
    expect(within(detail).getByText(/예상 비용 미제공/)).toBeTruthy();
    expect(
      within(detail).getByRole('button', { name: '다시 실행' }),
    ).toBeTruthy();
    expect(
      within(detail).queryByRole('button', { name: '작업 취소' }),
    ).toBeNull();

    await user.click(
      screen.getByRole('button', { name: '진행 중인 작업 보기' }),
    );
    expect(location()).toBe('/admin/pipeline?tab=jobs&job=job-running');
    expect(
      await within(detail).findByRole('button', { name: '작업 취소' }),
    ).toBeTruthy();
    expect(within(detail).getByText('처리 중')).toBeTruthy();
    expect(
      within(detail).queryByRole('button', { name: '다시 실행' }),
    ).toBeNull();
  });

  test('다시 실행은 사유를 받아 Idempotency-Key와 함께 보내고, 새 작업을 고른 뒤 목록을 다시 읽는다', async () => {
    const queued = job({
      id: 'job-retry',
      status: 'queued',
      retryOf: 'job-failed',
      startedAt: null,
      finishedAt: null,
      durationSeconds: null,
      report: null,
      error: null,
      retry: {
        allowed: false,
        code: 'in_progress',
        reason: '대기·실행 중인 작업이에요.',
        blockedBy: null,
      },
    });
    let retried = false;
    server.on('GET', JOBS, () =>
      json(list(retried ? [queued, job()] : [job()])),
    );
    server.on('GET', JOB, ({ params }) =>
      json(params.jobId === 'job-retry' ? queued : job()),
    );
    server.on('POST', RETRY, () => {
      retried = true;
      return json({ job: queued, deduplicated: false }, 202);
    });
    const { user, location } = open('/admin/pipeline?tab=jobs&job=job-failed');

    await user.click(await screen.findByRole('button', { name: '다시 실행' }));
    const form = screen.getByRole('form', { name: '작업 다시 실행' });
    await user.click(
      within(form).getByRole('button', { name: '다시 실행하기' }),
    );
    expect(within(form).getByText('사유를 입력해 주세요.')).toBeTruthy();
    expect(server.calls('POST', RETRY)).toHaveLength(0);
    expect(
      within(form)
        .getByLabelText('실행 사유(감사 로그에 남아요)')
        .getAttribute('maxLength'),
    ).toBe('500');

    await user.type(
      within(form).getByLabelText('실행 사유(감사 로그에 남아요)'),
      '  타임아웃 복구 확인  ',
    );
    await user.click(
      within(form).getByRole('button', { name: '다시 실행하기' }),
    );

    expect(
      await screen.findByText(
        '후보 재검증 작업을 다시 실행하도록 대기열에 넣었어요.',
      ),
    ).toBeTruthy();
    const [call] = server.calls('POST', RETRY);
    expect(call.params.jobId).toBe('job-failed');
    expect(call.body).toEqual({ reason: '타임아웃 복구 확인' });
    const [headers] = headersOf('/job-failed/retry');
    expect(headers.get('X-CSRF-Token')).toBe('csrf-admin');
    expect(headers.get('Idempotency-Key')).toBeTruthy();
    expect(location()).toBe('/admin/pipeline?tab=jobs&job=job-retry');
    expect(server.calls('GET', JOBS).length).toBeGreaterThan(1);
    const detail = screen.getByRole('complementary', { name: '작업 상세' });
    expect(await within(detail).findByText('job-failed')).toBeTruthy();
    expect(
      within(detail).getByRole('button', { name: '작업 취소' }),
    ).toBeTruthy();
  });

  test('재시도가 허용되지 않으면 서버가 준 이유와 막고 있는 작업을 보여 준다', async () => {
    const blocked = job({
      retry: {
        allowed: false,
        code: 'newer_attempt',
        reason: '더 새 재시도가 있어 가장 최근 시도만 다시 실행할 수 있어요.',
        blockedBy: 'job-newer',
      },
    });
    server.on('GET', JOBS, () => json(list([blocked])));
    server.on('GET', JOB, ({ params }) =>
      json(params.jobId === 'job-newer' ? job({ id: 'job-newer' }) : blocked),
    );
    const { user, location } = open('/admin/pipeline?tab=jobs&job=job-failed');

    const retry = await screen.findByRole('button', { name: '다시 실행' });
    expect((retry as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText(
        '다시 실행할 수 없어요. 더 새 재시도가 있어 가장 최근 시도만 다시 실행할 수 있어요.',
      ),
    ).toBeTruthy();
    expect(
      screen.getByText('실패하거나 취소된 작업만 다시 실행할 수 있어요.'),
    ).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'job-newer 보기' }));
    expect(location()).toBe('/admin/pipeline?tab=jobs&job=job-newer');
  });

  test('실행 중인 작업 취소는 요청 중 다른 작업을 고를 수 없고, 끝나면 취소 요청 상태를 보여 준다', async () => {
    const requested = { ...running, cancelRequested: true };
    let cancelled = false;
    server.on('GET', JOBS, () =>
      json(list([cancelled ? requested : running, job()])),
    );
    server.on('GET', JOB, () => json(cancelled ? requested : running));
    const response = deferred<Response>();
    server.on('POST', CANCEL, () => {
      cancelled = true;
      return response.promise;
    });
    const { user } = open('/admin/pipeline?tab=jobs&job=job-running');

    await user.click(await screen.findByRole('button', { name: '작업 취소' }));
    const form = screen.getByRole('form', { name: '작업 취소' });
    expect(
      within(form).getByText(/실행 중인 신규 기사 처리 작업에 취소를 요청해요/),
    ).toBeTruthy();
    await user.type(
      within(form).getByLabelText('취소 사유(감사 로그에 남아요)'),
      '잘못 시작함',
    );
    await user.click(
      within(form).getByRole('button', { name: '작업 취소하기' }),
    );

    expect(
      within(form).getByRole('button', { name: '취소하고 있어요' }),
    ).toBeTruthy();
    const table = screen.getByRole('table', { name: '작업 목록' });
    expect(
      (
        within(table).getByRole('button', {
          name: '후보 재검증',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);

    response.resolve(json(requested));
    expect(
      await screen.findByText('신규 기사 처리 작업에 취소를 요청했어요.'),
    ).toBeTruthy();
    expect(server.calls('POST', CANCEL)[0].body).toEqual({
      reason: '잘못 시작함',
    });
    expect(
      headersOf('/job-running/cancel')[0].get('Idempotency-Key'),
    ).toBeTruthy();
    const detail = screen.getByRole('complementary', { name: '작업 상세' });
    const button = await within(detail).findByRole('button', {
      name: '취소 요청됨',
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  test('이미 끝난 작업 취소(409)는 상태가 바뀌었다고 알리고, 같은 사유로 다시 보내면 새 키를 쓴다', async () => {
    server.on('GET', JOBS, () => json(list()));
    server.on('GET', JOB, () => json(running));
    server.on('POST', CANCEL, () => apiError(409, 'REVISION_CONFLICT'));
    const { user } = open('/admin/pipeline?tab=jobs&job=job-running');

    await user.click(await screen.findByRole('button', { name: '작업 취소' }));
    const form = screen.getByRole('form', { name: '작업 취소' });
    await user.type(
      within(form).getByLabelText('취소 사유(감사 로그에 남아요)'),
      '중복 실행',
    );
    await user.click(
      within(form).getByRole('button', { name: '작업 취소하기' }),
    );
    expect(
      await within(form).findByText(
        /이미 끝난 작업이라 취소할 수 없어요. 상세를 새로 고친 뒤 확인해 주세요./,
      ),
    ).toBeTruthy();

    await user.click(
      within(form).getByRole('button', { name: '작업 취소하기' }),
    );
    await within(form).findByRole('button', { name: '작업 취소하기' });
    const keys = headersOf('/job-running/cancel').map((headers) =>
      headers.get('Idempotency-Key'),
    );
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe(keys[1]);
  });

  test('작업이 없거나 상세를 읽지 못하면 그 상태를 알린다', async () => {
    server.on('GET', JOBS, () =>
      json({
        ...list([]),
        ingest: { ...list().ingest, at: null, unresolvedFailures: null },
      }),
    );
    server.on('GET', JOB, () => apiError(404, 'RESOURCE_NOT_FOUND'));
    open('/admin/pipeline?tab=jobs&job=job-gone');

    expect(await screen.findByText('아직 실행한 작업이 없어요.')).toBeTruthy();
    expect(screen.queryByText('기사 처리 기준 시점')).toBeNull();
    expect(
      await screen.findByText('작업 상세를 불러오지 못했어요'),
    ).toBeTruthy();
  });
});

async function fillPlan(user: UserEvent) {
  const form = await screen.findByRole('form', { name: '분석계획 접수' });
  await user.type(within(form).getByLabelText('planId'), planRef.planId);
  await user.type(
    within(form).getByLabelText('planDigest'),
    planRef.planDigest,
  );
  await user.type(
    within(form).getByLabelText('접수 사유(감사 로그에 남아요)'),
    '합성 계획 처리',
  );
  return form;
}

describe('A-ADM-03 분석계획 접수의 불확실성과 참조 불변식', () => {
  test('잘못된 참조는 전송하지 않고 오류 필드로 초점을 옮기며 입력을 유지한다', async () => {
    server.on('GET', JOBS, () => json(list([])));
    const { user } = open();
    const form = await screen.findByRole('form', { name: '분석계획 접수' });
    const input = within(form).getByLabelText('planId');
    await user.type(input, 'not-a-plan');
    await user.tab();
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(
      document.getElementById(input.getAttribute('aria-describedby')!),
    ).toBeTruthy();
    await user.click(
      within(form).getByRole('button', { name: '분석계획 접수' }),
    );
    expect(document.activeElement).toBe(input);
    expect((input as HTMLInputElement).value).toBe('not-a-plan');
    expect(server.calls('POST', JOBS)).toHaveLength(0);
  });

  test('응답 손실 후에는 입력을 잠그고 동일 본문과 키로만 접수 여부를 확인한다', async () => {
    server.on('GET', JOBS, () => json(list([])));
    server.on('GET', JOB, () => json(planJob()));
    const response = deferred<Response>();
    server.on('POST', JOBS, () => response.promise);
    const { user, location } = open();
    const form = await fillPlan(user);
    const submit = within(form).getByRole('button', { name: '분석계획 접수' });
    await user.dblClick(submit);
    expect(server.calls('POST', JOBS)).toHaveLength(1);
    await act(async () =>
      response.resolve(apiError(503, 'SOURCE_UNAVAILABLE')),
    );
    const confirm = await within(form).findByRole('button', {
      name: '같은 요청 확인',
    });
    expect(
      (within(form).getByLabelText('planId') as HTMLInputElement).disabled,
    ).toBe(true);
    expect(
      (
        within(form).getByLabelText(
          '접수 사유(감사 로그에 남아요)',
        ) as HTMLTextAreaElement
      ).value,
    ).toBe('합성 계획 처리');
    expect(location()).toBe('/admin/pipeline?tab=jobs');
    server.on('POST', JOBS, () =>
      json({ job: planJob(), deduplicated: false }, 202),
    );
    await user.click(confirm);
    await screen.findByRole('heading', { name: /분석계획.*job-plan/ });
    const calls = server.calls('POST', JOBS);
    expect(calls).toHaveLength(2);
    expect(calls[0].body).toEqual({
      kind: 'analyze_plan',
      plan: planRef,
      reason: '합성 계획 처리',
    });
    expect(calls[1].body).toEqual(calls[0].body);
    const keys = headersOf('/admin/jobs').filter((headers) =>
      headers.has('Idempotency-Key'),
    );
    expect(keys).toHaveLength(2);
    expect(keys[0].get('Idempotency-Key')).toBe(keys[1].get('Idempotency-Key'));
    expect(keys[0].get('X-CSRF-Token')).toBe('csrf-admin');
    expect(location()).toBe('/admin/pipeline?tab=jobs&job=job-plan');
  });

  test.each(['kind', 'digest'] as const)(
    '다른 %s에 묶인 생성 응답은 선택하지 않고 원래 접수 요청을 유지한다',
    async (mismatch) => {
      server.on('GET', JOBS, () => json(list([])));
      server.on('POST', JOBS, () =>
        json(
          {
            job:
              mismatch === 'kind'
                ? job()
                : planJob({
                    planRun: {
                      ...planJob().planRun,
                      planDigest: 'c'.repeat(64),
                    },
                  }),
            deduplicated: false,
          },
          202,
        ),
      );
      const { user, location } = open();
      const form = await fillPlan(user);
      await user.click(
        within(form).getByRole('button', { name: '분석계획 접수' }),
      );
      await within(form).findByRole('button', { name: '같은 요청 확인' });
      expect(location()).toBe('/admin/pipeline?tab=jobs');
      expect(server.calls('GET', JOB)).toHaveLength(0);
      expect(
        (within(form).getByLabelText('planDigest') as HTMLInputElement).value,
      ).toBe(planRef.planDigest);
    },
  );

  test.each(['session', 'disposal'] as const)(
    '%s 이후 도착한 접수 응답은 선택·결과에 반영하지 않는다',
    async (change) => {
      server.on('GET', JOBS, () => json(list([])));
      const response = deferred<Response>();
      server.on('POST', JOBS, () => response.promise);
      const rendered = open();
      const form = await fillPlan(rendered.user);
      await rendered.user.click(
        within(form).getByRole('button', { name: '분석계획 접수' }),
      );
      if (change === 'session') {
        act(() => useAdminSessionStore.getState().setSession(signedIn));
        const fresh = await screen.findByRole('form', {
          name: '분석계획 접수',
        });
        expect(
          (within(fresh).getByLabelText('planId') as HTMLInputElement).value,
        ).toBe('');
      } else cleanup();
      await act(async () =>
        response.resolve(json({ job: planJob(), deduplicated: false }, 202)),
      );
      expect(rendered.location()).toBe('/admin/pipeline?tab=jobs');
      expect(
        screen.queryByText(
          '분석계획을 대기열에 접수했어요. 아직 AI 처리 완료는 아니에요.',
        ),
      ).toBeNull();
      expect(server.calls('GET', JOB)).toHaveLength(0);
    },
  );

  test.each([
    'worker_unavailable',
    'plan_not_reusable',
    'outcome_unknown',
  ] as const)(
    '%s 상태에서 새 실행을 보내지 않고 부분 진행과 기존 수집 기준을 보존한다',
    async (code) => {
      const failed = planJob({
        status: 'failed',
        retry: { allowed: false, code, reason: code, blockedBy: null },
        planRun: {
          ...planJob().planRun,
          phase: 'failed',
          readyUnits: 1,
          totalUnits: 3,
        },
      });
      server.on('GET', JOBS, () => json(list([failed])));
      server.on('GET', JOB, () => json(failed));
      const { user } = open('/admin/pipeline?tab=jobs&job=job-plan');
      const retry = await screen.findByRole('button', { name: '이어서 처리' });
      expect((retry as HTMLButtonElement).disabled).toBe(true);
      await user.click(retry);
      expect(server.calls('POST', RETRY)).toHaveLength(0);
      const detail = screen.getByRole('complementary', { name: '작업 상세' });
      expect(within(detail).getByText('1 / 3')).toBeTruthy();
      expect(within(detail).getByText('없음')).toBeTruthy();
      expect(
        within(detail).queryByRole('region', { name: '기사 처리 결과' }),
      ).toBeNull();
      expect(
        within(detail).queryByRole('region', { name: '모델 사용량' }),
      ).toBeNull();
      expect(screen.getByText(/새 기사 없음/)).toBeTruthy();
    },
  );

  test('접수 전 전체 단위와 진행 순번은 0으로 추정하지 않는다', async () => {
    server.on('GET', JOBS, () => json(list([planJob()])));
    server.on('GET', JOB, () => json(planJob()));
    open('/admin/pipeline?tab=jobs&job=job-plan');
    const detail = await screen.findByRole('complementary', {
      name: '작업 상세',
    });
    expect(await within(detail).findByText('0 / –')).toBeTruthy();
    expect(
      within(detail).getByText('진행 단위 순번').nextElementSibling
        ?.textContent,
    ).toBe('–');
  });
});

describe('A-ADM-03 분석계획 계속 처리·취소 불변식', () => {
  test('계속 처리 응답 손실은 사유와 키를 유지하고 완료된 원본 계획의 참조를 바꾸지 않는다', async () => {
    const failed = planJob({
      status: 'failed',
      retry: { allowed: true, code: 'allowed', reason: '', blockedBy: null },
      planRun: {
        ...planJob().planRun,
        phase: 'failed',
        readyUnits: 1,
        totalUnits: 2,
      },
    });
    const queued = planJob({ id: 'job-plan-retry', retryOf: failed.id });
    server.on('GET', JOBS, () => json(list([failed])));
    server.on('GET', JOB, ({ params }) =>
      json(params.jobId === queued.id ? queued : failed),
    );
    server.on('POST', RETRY, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user, location } = open('/admin/pipeline?tab=jobs&job=job-plan');
    await user.click(
      await screen.findByRole('button', { name: '이어서 처리' }),
    );
    const form = screen.getByRole('form', { name: '분석계획 이어서 처리' });
    const reason = within(form).getByLabelText('처리 사유(감사 로그에 남아요)');
    await user.type(reason, '일시 장애 후 계속 처리');
    await user.click(
      within(form).getByRole('button', { name: '이어서 처리하기' }),
    );
    await within(form).findByRole('button', { name: '같은 요청 확인' });
    expect((reason as HTMLTextAreaElement).disabled).toBe(true);
    expect(
      (within(form).getByRole('button', { name: '닫기' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole('button', {
          name: '진행 상태 새로 고침',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    server.on('POST', RETRY, () =>
      json({ job: queued, deduplicated: false }, 202),
    );
    await user.click(
      within(form).getByRole('button', { name: '같은 요청 확인' }),
    );
    await screen.findByRole('heading', { name: /job-plan-retry/ });
    const calls = server.calls('POST', RETRY);
    expect(calls).toHaveLength(2);
    expect(calls[0].body).toEqual({ reason: '일시 장애 후 계속 처리' });
    expect(calls[1].body).toEqual(calls[0].body);
    expect(calls[0].headers.get('Idempotency-Key')).toBe(
      calls[1].headers.get('Idempotency-Key'),
    );
    expect(location()).toBe('/admin/pipeline?tab=jobs&job=job-plan-retry');
  });

  test('실행 중 취소 응답은 종료로 바꾸지 않고 새 조회에서만 종료와 부분 진행을 반영한다', async () => {
    let current = planJob({
      status: 'running',
      startedAt: '2026-10-23T01:00:05Z',
      planRun: {
        ...planJob().planRun,
        phase: 'relating',
        readyUnits: 1,
        totalUnits: 2,
        activeUnit: 2,
      },
    });
    server.on('GET', JOBS, () => json(list([current])));
    server.on('GET', JOB, () => json(current));
    server.on('POST', CANCEL, () => {
      current = {
        ...current,
        cancelRequested: true,
        planRun: { ...current.planRun, phase: 'cancelling' },
      };
      return json(current);
    });
    const { user } = open('/admin/pipeline?tab=jobs&job=job-plan');
    await user.click(await screen.findByRole('button', { name: '작업 취소' }));
    const form = screen.getByRole('form', { name: '작업 취소' });
    await user.type(
      within(form).getByLabelText('취소 사유(감사 로그에 남아요)'),
      '처리 중단 요청',
    );
    await user.click(
      within(form).getByRole('button', { name: '작업 취소하기' }),
    );
    expect(
      await screen.findByRole('button', { name: '취소 요청됨' }),
    ).toBeTruthy();
    const detail = screen.getByRole('complementary', { name: '작업 상세' });
    expect(within(detail).getByText('1 / 2')).toBeTruthy();
    expect(within(detail).queryByText('취소됨')).toBeNull();
    current = {
      ...current,
      status: 'cancelled',
      planRun: { ...current.planRun, phase: 'cancelled' },
    };
    await user.click(
      within(detail).getByRole('button', { name: '진행 상태 새로 고침' }),
    );
    expect(await within(detail).findByText('취소됨')).toBeTruthy();
    expect(within(detail).getByText('1 / 2')).toBeTruthy();
  });
});
