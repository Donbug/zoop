import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import AdminBriefingsPage from '@/pages/admin/briefings/AdminBriefingsPage';
import AdminAiPage from '@/pages/admin/ai/AdminAiPage';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type {
  AdminRound,
  AiFeatureUsage,
  AiUsage,
  RoundDetail,
} from '@/types/admin/briefings';
import {
  apiError,
  createFakeServer,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const SESSION = '/api/v1/admin/auth/session';
const ROUNDS = '/api/v1/admin/briefings';
const ROUND = '/api/v1/admin/briefings/:roundId';
const REPROCESS = '/api/v1/admin/briefings/:roundId/reprocess';
const CORRECTIONS = '/api/v1/admin/briefings/:roundId/corrections';
const SUSPENSION = '/api/v1/admin/briefings/:roundId/suspension';
const AI_USAGE = '/api/v1/admin/ai-usage';

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

// 이하 합성 fixture. 와이어프레임 A-ADM-04·04b의 예시를 따른다.
const stage = (status: 'done' | 'failed' | 'pending') => ({ status, at: null });

function round(overrides: Partial<AdminRound> = {}): AdminRound {
  return {
    id: 'r-0606-m',
    date: '2026-10-06',
    edition: 'morning',
    scheduledAt: '2026-10-05T22:40:00Z',
    dataWindow: {
      start: '2026-10-05T09:10:00Z',
      end: '2026-10-05T22:40:00Z',
      openStart: false,
    },
    status: 'published',
    stages: {
      generate: stage('done'),
      verify: stage('done'),
      publish: stage('done'),
    },
    failureReason: null,
    generatedAt: '2026-10-05T22:40:10Z',
    publishedAt: '2026-10-05T22:40:20Z',
    graphVersion: 'v1',
    reviewRevision: 11,
    itemCount: 2,
    trigger: 'scheduler',
    attempts: 1,
    delayed: false,
    correctionCount: 0,
    suspension: null,
    reprocessable: false,
    blockedReason: '이미 발행한 회차예요.',
    ...overrides,
  };
}

const failed = round({
  id: 'r-0605-e',
  date: '2026-10-05',
  edition: 'evening',
  status: 'failed',
  stages: {
    generate: stage('failed'),
    verify: stage('pending'),
    publish: stage('pending'),
  },
  failureReason: '원장 연결 실패',
  publishedAt: null,
  reprocessable: true,
  blockedReason: null,
});

function detail(base: AdminRound, overrides: Partial<RoundDetail> = {}) {
  return {
    ...base,
    published:
      base.status === 'published' || base.status === 'suspended'
        ? {
            id: base.id,
            items: [
              {
                eventId: 'ev-1',
                rank: 1,
                title: '반도체 수출 규제 발표',
                reason: '관련 기업 3곳',
              },
            ],
          }
        : null,
    corrections: [],
    attemptsLog: [
      {
        n: 1,
        trigger: 'scheduler',
        startedAt: '2026-10-05T22:40:00Z',
        finishedAt: '2026-10-05T22:40:20Z',
        status: base.status,
        failureReason: base.failureReason,
        adminEmail: null,
      },
    ],
    ...overrides,
  } satisfies RoundDetail;
}

function feature(overrides: Partial<AiFeatureUsage>): AiFeatureUsage {
  return {
    feature: 'chatbot',
    label: 'AI 챗봇',
    engine: 'BFF 규칙 기반 답변 · 모델 호출 없음',
    modelBacked: false,
    requests: 2,
    succeeded: 2,
    failed: 0,
    latencyMs: { avg: 14, p95: 16, max: 20 },
    usage: {
      modelCalls: 0,
      inputTokens: 0,
      outputTokens: 0,
      replayCalls: 0,
      retries: 0,
    },
    cost: {
      status: 'unavailable',
      actual: null,
      estimated: null,
      currency: null,
      reason: '단가 기준이 정해지지 않았어요.',
    },
    source: 'measured',
    recentErrors: [],
    note: '',
    ...overrides,
  };
}

const aiUsage: AiUsage = {
  asOf: '2026-10-06T03:45:01Z',
  window: '7d',
  cost: {
    status: 'unavailable',
    actual: null,
    estimated: null,
    currency: null,
    reason: '단가 기준이 정해지지 않았어요',
  },
  features: [
    feature({ note: '규칙 기반이라 모델을 부르지 않아요.' }),
    feature({
      feature: 'news-analysis',
      label: '뉴스 분석(PoC 파이프라인)',
      engine: 'InvestMate PoC · 모델 호출(유료)',
      modelBacked: true,
      requests: 0,
      succeeded: 0,
      latencyMs: null,
      usage: {
        modelCalls: null,
        inputTokens: null,
        outputTokens: 1200,
        replayCalls: 3,
        retries: 1,
      },
      cost: {
        status: 'estimated',
        actual: 0.42,
        estimated: 0.5,
        currency: 'USD',
        reason: '',
      },
      source: 'ledger-db',
    }),
  ],
  pastRuns: [],
};

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
          { path: '/admin/briefings', element: <AdminBriefingsPage /> },
          { path: '/admin/ai', element: <AdminAiPage /> },
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
  server.on('GET', ROUNDS, () =>
    json({
      items: [round(), failed],
      schedule: { morning: '07:40', evening: '18:10', timezone: 'Asia/Seoul' },
      nextCursor: null,
    }),
  );
  server.on('GET', ROUND, (request) =>
    json(
      request.params.roundId === failed.id ? detail(failed) : detail(round()),
    ),
  );
});

describe('A-ADM-04 브리핑 운영 (FS070·FS071)', () => {
  test('회차 목록과 예정 시각을 보여 주고, 회차를 고르면 상세를 연다', async () => {
    const { user, location } = open('/admin/briefings');

    const table = await screen.findByRole('table', { name: '브리핑 회차' });
    expect(screen.getByText('예정 출근 07:40 · 퇴근 18:10 (KST)')).toBeTruthy();
    expect(within(table).getByText('2026-10-06 출근')).toBeTruthy();
    expect(within(table).getByText('발행됨')).toBeTruthy();
    expect(within(table).getByText('원장 연결 실패')).toBeTruthy();
    expect(screen.getByText('회차를 골라 주세요')).toBeTruthy();

    await user.click(
      within(table).getByRole('button', { name: '2026-10-06 출근' }),
    );

    expect(location()).toBe('/admin/briefings?round=r-0606-m');
    const panel = await screen.findByRole('article', { name: '회차 상세' });
    expect(
      await within(panel).findByText('반도체 수출 규제 발표'),
    ).toBeTruthy();
    expect(within(panel).getByText('등록된 정정이 없어요.')).toBeTruthy();
    expect(within(panel).getByText('생성 완료')).toBeTruthy();
    expect(
      within(panel).getByText('재처리할 수 없어요: 이미 발행한 회차예요.'),
    ).toBeTruthy();
    expect(
      (
        within(panel).getByRole('button', {
          name: '재처리',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      within(panel).getByRole('table', { name: '회차 처리 기록' }),
    ).toBeTruthy();
  });

  test('실패한 미발행 회차를 사유와 함께 재처리하고 상세와 목록을 다시 읽는다', async () => {
    server.on('POST', REPROCESS, () =>
      json(round({ ...failed, status: 'generating' }), 202),
    );
    const { user } = open(`/admin/briefings?round=${failed.id}`);
    const panel = await screen.findByRole('article', { name: '회차 상세' });
    expect(
      await within(panel).findByText('실패 사유: 원장 연결 실패'),
    ).toBeTruthy();
    expect(within(panel).getByText('발행된 원문이 없어요.')).toBeTruthy();

    await user.click(within(panel).getByRole('button', { name: '재처리' }));
    const form = within(panel).getByRole('form', { name: '브리핑 재처리' });
    await user.click(within(form).getByRole('button', { name: '재처리 요청' }));
    expect(within(form).getByText('사유를 입력해 주세요.')).toBeTruthy();
    expect(server.calls('POST', REPROCESS)).toHaveLength(0);

    await user.type(within(form).getByLabelText('재처리 사유'), '원장 복구됨');
    await user.click(within(form).getByRole('button', { name: '재처리 요청' }));

    expect(await within(panel).findByText('재처리를 요청했어요.')).toBeTruthy();
    expect(server.calls('POST', REPROCESS)[0].body).toEqual({
      reason: '원장 복구됨',
    });
    const [headers] = headersOf('/reprocess');
    expect(headers.get('X-CSRF-Token')).toBe('csrf-admin');
    expect(headers.get('Idempotency-Key')).toBeTruthy();
    await waitFor(() =>
      expect(server.calls('GET', ROUND).length).toBeGreaterThanOrEqual(2),
    );
    expect(server.calls('GET', ROUNDS).length).toBeGreaterThanOrEqual(2);
  });

  async function openReprocessForm(reason: string) {
    const { user } = open(`/admin/briefings?round=${failed.id}`);
    const panel = await screen.findByRole('article', { name: '회차 상세' });
    await user.click(
      await within(panel).findByRole('button', { name: '재처리' }),
    );
    const form = within(panel).getByRole('form', { name: '브리핑 재처리' });
    await user.type(within(form).getByLabelText('재처리 사유'), reason);
    const submit = () =>
      user.click(within(form).getByRole('button', { name: '재처리 요청' }));
    await submit();
    return { user, panel, form, submit };
  }

  const reprocessKeys = () =>
    headersOf('/reprocess').map((headers) => headers.get('Idempotency-Key'));

  test('응답을 받지 못해 같은 내용을 다시 보내면 같은 Idempotency-Key를 쓴다', async () => {
    let attempts = 0;
    server.on('POST', REPROCESS, () => {
      attempts += 1;
      return attempts === 1
        ? apiError(503, 'SOURCE_UNAVAILABLE')
        : json(round(failed), 202);
    });
    const { panel, form, submit } = await openReprocessForm('다시');

    expect(
      await within(form).findByText(
        '브리핑 재처리에 실패했어요. 집계 서버에 연결하지 못했어요.',
      ),
    ).toBeTruthy();
    await submit();
    expect(await within(panel).findByText('재처리를 요청했어요.')).toBeTruthy();

    const keys = reprocessKeys();
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  test('서버가 거절(409)한 뒤나 내용을 바꿔 다시 보내면 새 Idempotency-Key를 쓴다', async () => {
    let attempts = 0;
    server.on('POST', REPROCESS, () => {
      attempts += 1;
      return attempts === 1
        ? apiError(409, 'REVISION_CONFLICT')
        : attempts === 2
          ? apiError(503, 'SOURCE_UNAVAILABLE')
          : json(round(failed), 202);
    });
    const { user, panel, form, submit } = await openReprocessForm('다시');

    expect(
      await within(form).findByText(
        '브리핑 재처리에 실패했어요. 상태가 바뀌어 처리하지 못했어요. 화면을 새로 고친 뒤 다시 시도해 주세요.',
      ),
    ).toBeTruthy();
    await submit();
    await within(form).findByText(/집계 서버에 연결하지 못했어요/);
    await user.type(within(form).getByLabelText('재처리 사유'), ' 확인');
    await submit();
    expect(await within(panel).findByText('재처리를 요청했어요.')).toBeTruthy();

    const keys = reprocessKeys();
    expect(keys).toHaveLength(3);
    expect(new Set(keys).size).toBe(3);
    expect(server.calls('POST', REPROCESS)[2].body).toEqual({
      reason: '다시 확인',
    });
  });

  test('발행 회차에 원문을 유지한 정정을 등록한다', async () => {
    server.on('POST', CORRECTIONS, () =>
      json(
        {
          id: 1,
          seq: 1,
          eventId: 'ev-1',
          original: '반도체 수출 규제 발표',
          corrected: '반도체 수출 규제 검토',
          reason: '확정 전 보도',
          createdAt: '2026-10-06T01:00:00Z',
          adminEmail: 'admin@zoop.test',
        },
        201,
      ),
    );
    const { user } = open('/admin/briefings?round=r-0606-m');
    const panel = await screen.findByRole('article', { name: '회차 상세' });
    await user.click(
      await within(panel).findByRole('button', { name: '정정 등록' }),
    );
    const form = within(panel).getByRole('form', { name: '정정 등록' });

    await user.selectOptions(
      within(form).getByLabelText('정정할 항목'),
      'ev-1',
    );
    await user.type(within(form).getByLabelText('정정 사유'), '확정 전 보도');
    await user.click(
      within(form).getByRole('button', { name: '정정 등록하기' }),
    );
    expect(
      within(form).getByText('정정 내용과 사유를 모두 입력해 주세요.'),
    ).toBeTruthy();

    await user.type(
      within(form).getByLabelText('정정 내용'),
      '반도체 수출 규제 검토',
    );
    await user.click(
      within(form).getByRole('button', { name: '정정 등록하기' }),
    );

    expect(await within(panel).findByText('정정을 등록했어요.')).toBeTruthy();
    expect(server.calls('POST', CORRECTIONS)[0].body).toEqual({
      eventId: 'ev-1',
      correctedText: '반도체 수출 규제 검토',
      reason: '확정 전 보도',
    });
  });

  test('발행 회차의 제공을 중단하고, 중단된 회차는 재개할 수 있다', async () => {
    server.on('POST', SUSPENSION, () => json(round({ status: 'suspended' })));
    const { user } = open('/admin/briefings?round=r-0606-m');
    const panel = await screen.findByRole('article', { name: '회차 상세' });
    await user.click(
      await within(panel).findByRole('button', { name: '제공 중단' }),
    );
    const form = within(panel).getByRole('form', { name: '제공 중단' });
    expect(
      within(form).getByText(/중단 사유는 사용자 화면에 그대로 보여요/),
    ).toBeTruthy();
    await user.type(
      within(form).getByLabelText('사용자에게 보일 중단 사유'),
      '내용 확인 중',
    );
    server.on('GET', ROUND, () =>
      json(
        detail(round({ status: 'suspended' }), {
          suspension: {
            reason: '내용 확인 중',
            at: '2026-10-06T01:00:00Z',
            adminEmail: 'admin@zoop.test',
          },
        }),
      ),
    );
    await user.click(
      within(form).getByRole('button', { name: '제공 중단하기' }),
    );

    expect(await within(panel).findByText('제공을 중단했어요.')).toBeTruthy();
    expect(server.calls('POST', SUSPENSION)[0].body).toEqual({
      action: 'suspend',
      reason: '내용 확인 중',
    });
    expect(
      await within(panel).findByRole('button', { name: '제공 재개' }),
    ).toBeTruthy();
    expect(within(panel).getByText(/제공 중단: 내용 확인 중/)).toBeTruthy();
  });

  test('목록 조회에 실패하면 다시 시도할 수 있다', async () => {
    let attempts = 0;
    server.on('GET', ROUNDS, () => {
      attempts += 1;
      return attempts === 1
        ? apiError(503, 'SOURCE_UNAVAILABLE')
        : json({
            items: [round()],
            schedule: {
              morning: '07:40',
              evening: '18:10',
              timezone: 'Asia/Seoul',
            },
            nextCursor: null,
          });
    });
    const { user } = open('/admin/briefings');

    const alert = await screen.findByRole('alert');
    expect(
      within(alert).getByText('집계 서버에 연결하지 못했어요.'),
    ).toBeTruthy();
    await user.click(within(alert).getByRole('button', { name: '다시 시도' }));
    expect(
      await screen.findByRole('table', { name: '브리핑 회차' }),
    ).toBeTruthy();
  });
});

describe('A-ADM-04b AI 사용량·오류 (FS068)', () => {
  test('기능별 사용량에서 모르는 값은 0이 아니라 –로, 비용은 실제·추정을 구분한다', async () => {
    server.on('GET', AI_USAGE, () => json(aiUsage));
    open('/admin/ai');

    const table = await screen.findByRole('table', {
      name: 'AI 기능별 사용량',
    });
    const rows = within(table).getAllByRole('row');
    const chat = within(rows[1]);
    expect(chat.getByText('AI 챗봇')).toBeTruthy();
    expect(chat.getByText('14ms')).toBeTruthy();
    expect(chat.getByText('미제공')).toBeTruthy();
    expect(chat.getByText('BFF 실측')).toBeTruthy();

    const news = within(rows[2]);
    expect(news.getAllByText('–').length).toBeGreaterThanOrEqual(4);
    expect(news.getByText('1,200')).toBeTruthy();
    expect(news.getByText('실제 0.42 USD')).toBeTruthy();
    expect(news.getByText('추정 0.5 USD')).toBeTruthy();
    expect(news.getByText('작업 원장')).toBeTruthy();

    expect(
      screen.getByText('ⓘ AI 챗봇: 규칙 기반이라 모델을 부르지 않아요.'),
    ).toBeTruthy();
    expect(screen.getByText('이 기간에 기록된 오류가 없어요.')).toBeTruthy();
    expect(
      screen.getByText(/비용 미제공\(단가 기준이 정해지지 않았어요\)/),
    ).toBeTruthy();
    expect(server.calls('GET', AI_USAGE)[0].query.get('window')).toBe('7d');
  });

  test('기간을 바꾸면 다시 조회하고, 최근 오류를 기능과 함께 보여 준다', async () => {
    server.on('GET', AI_USAGE, (request) =>
      json({
        ...aiUsage,
        window: request.query.get('window'),
        features: [
          feature({
            recentErrors: [
              {
                at: '2026-10-06T02:00:00Z',
                code: 'MODEL_TIMEOUT',
                message: '응답 시간 초과',
              },
            ],
          }),
        ],
      }),
    );
    const { user, location } = open('/admin/ai');
    await screen.findByRole('table', { name: 'AI 기능별 사용량' });

    await user.click(screen.getByRole('button', { name: '24시간' }));
    expect(location()).toBe('/admin/ai?window=24h');
    await waitFor(() =>
      expect(server.calls('GET', AI_USAGE).at(-1)?.query.get('window')).toBe(
        '24h',
      ),
    );
    const errors = await screen.findByRole('table', { name: 'AI 최근 오류' });
    expect(within(errors).getByText('MODEL_TIMEOUT')).toBeTruthy();
    expect(within(errors).getByText('응답 시간 초과')).toBeTruthy();
  });

  test('날짜별·회원 수 자료가 아직 없으면 그래프 대신 아직 제공하지 않는다고 알린다', async () => {
    server.on('GET', AI_USAGE, () => json(aiUsage));
    open('/admin/ai');
    await screen.findByRole('table', { name: 'AI 기능별 사용량' });
    expect(
      screen.getAllByText('AI 사용량 API가 아직 이 값을 주지 않아요.'),
    ).toHaveLength(3);
    expect(screen.queryByRole('group', { name: /날짜별/ })).toBeNull();
  });

  test('전체·브리핑·AI 챗봇 보기로 회원 사용 비율과 날짜별 토큰·비용을 나눠 보여 준다', async () => {
    server.on('GET', AI_USAGE, () =>
      json({
        ...aiUsage,
        cost: { ...aiUsage.cost, currency: 'USD' },
        features: [
          feature({
            usage: {
              modelCalls: 10,
              inputTokens: 3000,
              outputTokens: 1000,
              replayCalls: 0,
              retries: 0,
            },
          }),
          feature({
            feature: 'briefing',
            label: '출퇴근 브리핑',
            usage: {
              modelCalls: 2,
              inputTokens: 900,
              outputTokens: 100,
              replayCalls: 0,
              retries: 0,
            },
          }),
        ],
        members: {
          totalMembers: 200,
          aiMembers: 50,
          chatbotMembers: 30,
          briefingMembers: null,
          note: null,
        },
        daily: [
          {
            date: '2026-10-24',
            features: [
              {
                feature: 'chatbot',
                modelCalls: 6,
                inputTokens: 2000,
                outputTokens: 600,
                actualCost: null,
                estimatedCost: 0.03,
              },
              {
                feature: 'briefing',
                modelCalls: 1,
                inputTokens: 500,
                outputTokens: 50,
                actualCost: 0.01,
                estimatedCost: 0.012,
              },
            ],
          },
          {
            date: '2026-10-23',
            features: [
              {
                feature: 'chatbot',
                modelCalls: 4,
                inputTokens: 1000,
                outputTokens: 400,
                actualCost: null,
                estimatedCost: 0.02,
              },
              {
                feature: 'briefing',
                modelCalls: null,
                inputTokens: null,
                outputTokens: null,
                actualCost: null,
                estimatedCost: null,
              },
            ],
          },
        ],
      }),
    );
    const { user, location } = open('/admin/ai');

    expect(await screen.findByText('25%')).toBeTruthy();
    expect(screen.getByText('50명 / 전체 200명')).toBeTruthy();
    expect(
      screen.getByRole('meter', { name: 'AI 기능을 쓴 회원 비율' }),
    ).toBeTruthy();
    const tokens = screen.getByRole('group', {
      name: '전체 날짜별 토큰 사용량 (←→로 날짜 이동)',
    });
    // 날짜는 오래된 것부터 그린다.
    const bars = within(tokens).getAllByRole('img');
    expect(bars[0].getAttribute('aria-label')).toBe(
      '10월 23일 입력 자료 없음, 출력 자료 없음, 모델 호출 자료 없음',
    );
    expect(bars[1].getAttribute('aria-label')).toBe(
      '10월 24일 입력 2,500, 출력 650, 모델 호출 7',
    );
    expect(
      screen.getByRole('list', { name: '기능별 토큰 비중' }).textContent,
    ).toContain('80%');

    // 키보드: 그래프는 Tab 한 칸(마지막 날)이고, ←로 앞 날짜로 옮기면 값 읽기 줄도 바뀐다.
    expect(bars.map((bar) => bar.getAttribute('tabindex'))).toEqual([
      '-1',
      '0',
    ]);
    bars[1].focus();
    await user.keyboard('{ArrowLeft}');
    expect(document.activeElement).toBe(bars[0]);
    expect(bars[0].getAttribute('tabindex')).toBe('0');
    expect(bars[1].getAttribute('tabindex')).toBe('-1');
    expect(tokens.parentElement?.parentElement?.textContent).toContain(
      '10월 23일 입력 자료 없음 · 출력 자료 없음 · 모델 호출 자료 없음',
    );
    await user.keyboard('{End}');
    expect(document.activeElement).toBe(bars[1]);

    // 실제 청구액이 있는 기능(브리핑)과 추정만 있는 기능(챗봇)을 함께 더한다.
    const allCost = screen.getByRole('group', {
      name: '전체 날짜별 AI 비용 (←→로 날짜 이동)',
    });
    expect(
      within(allCost).getAllByRole('img')[1].getAttribute('aria-label'),
    ).toBe('10월 24일 실제+추정 0.04 USD');

    await user.click(screen.getByRole('tab', { name: '브리핑' }));
    expect(location()).toBe('/admin/ai?view=briefing');
    expect(screen.getByText('측정 안 함 / 전체 200명')).toBeTruthy();
    const briefing = screen.getByRole('group', {
      name: '브리핑 날짜별 토큰 사용량 (←→로 날짜 이동)',
    });
    const briefingBars = within(briefing).getAllByRole('img');
    expect(briefingBars[0].getAttribute('aria-label')).toBe(
      '10월 23일 입력 자료 없음, 출력 자료 없음, 모델 호출 자료 없음',
    );
    const cost = screen.getByRole('group', {
      name: '브리핑 날짜별 AI 비용 (←→로 날짜 이동)',
    });
    expect(within(cost).getAllByRole('img')[1].getAttribute('aria-label')).toBe(
      '10월 24일 실제 0.01 USD',
    );
    expect(screen.getByText(/실제 청구 비용이에요/)).toBeTruthy();
    const table = screen.getByRole('table', { name: 'AI 기능별 사용량' });
    expect(within(table).getByText('출퇴근 브리핑')).toBeTruthy();
    expect(within(table).queryByText('AI 챗봇')).toBeNull();
    expect(screen.queryByRole('list', { name: '기능별 토큰 비중' })).toBeNull();

    await user.click(screen.getByRole('tab', { name: 'AI 챗봇' }));
    expect(screen.getByText('15%')).toBeTruthy();
    const chatCost = screen.getByRole('group', {
      name: 'AI 챗봇 날짜별 AI 비용 (←→로 날짜 이동)',
    });
    expect(
      within(chatCost).getAllByRole('img')[0].getAttribute('aria-label'),
    ).toBe('10월 23일 추정 0.02 USD');
    expect(
      screen.getByText(/추정 비용이에요. 실제 청구액과 다를 수 있어요/),
    ).toBeTruthy();
  });

  test('일부 기능의 토큰을 모르면 부분합으로 기능 비중을 만들지 않는다', async () => {
    server.on('GET', AI_USAGE, () =>
      json({
        ...aiUsage,
        features: [
          feature({
            usage: {
              modelCalls: 2,
              inputTokens: 900,
              outputTokens: 100,
              replayCalls: 0,
              retries: 0,
            },
          }),
          feature({
            feature: 'news-analysis',
            label: '뉴스 분석',
            usage: {
              modelCalls: null,
              inputTokens: null,
              outputTokens: null,
              replayCalls: 0,
              retries: 0,
            },
          }),
        ],
      }),
    );
    open('/admin/ai');

    const share = await screen.findByRole('list', {
      name: '기능별 토큰 비중',
    });
    expect(
      screen.getByText(
        '일부 기능의 토큰 자료가 없어 전체 토큰과 기능별 비중을 계산하지 않아요.',
      ),
    ).toBeTruthy();
    expect(share.textContent).toContain('1천');
    expect(share.textContent).toContain('자료 없음');
    expect(share.textContent).not.toContain('%');
  });
});
