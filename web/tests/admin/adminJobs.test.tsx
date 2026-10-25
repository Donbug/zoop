import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import AdminPipelinePage from '@/pages/admin/pipeline/AdminPipelinePage';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type { AnalysisJob, JobList } from '@/types/admin/jobs';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

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

function job(overrides: Partial<AnalysisJob> = {}): AnalysisJob {
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
