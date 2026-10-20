import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import AdminStatsPage from '@/pages/admin/stats/AdminStatsPage';
import AdminCompanyStatsPage from '@/pages/admin/stats/AdminCompanyStatsPage';
import AdminFeedbackPage from '@/pages/admin/feedback/AdminFeedbackPage';
import AdminTranscriptPage from '@/pages/admin/feedback/AdminTranscriptPage';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import type {
  FeedbackSummary,
  InsightCompanyDetail,
  StatsMetric,
  StatsSummary,
  TranscriptDetail,
} from '@/types/admin/insights';
import {
  apiError,
  createFakeServer,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const SESSION = '/api/v1/admin/auth/session';
const SUMMARY = '/api/v1/admin/insights/summary';
const COMPANIES = '/api/v1/admin/insights/companies';
const COMPANY = '/api/v1/admin/insights/companies/:companyId';
const FEEDBACK = '/api/v1/admin/feedback/summary';
const DISLIKES = '/api/v1/admin/feedback/dislikes';
const TRANSCRIPTS = '/api/v1/admin/transcripts';
const TRANSCRIPT = '/api/v1/admin/transcripts/:sessionId';

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

// 이하 합성 fixture. 와이어프레임 A-ADM-02·02b의 예시 수치를 따른다.
function metric(overrides: Partial<StatsMetric>): StatsMetric {
  return {
    key: 'm',
    group: 'usage',
    label: '지표',
    kind: 'count',
    unit: '명',
    definition: '정의',
    count: 0,
    numerator: null,
    denominator: null,
    rate: null,
    sampleHidden: false,
    ...overrides,
  };
}

const summary: StatsSummary = {
  window: '7d',
  asOf: '2026-10-06T03:44:13Z',
  since: '2026-09-30',
  minSample: 5,
  membersScope: '가입일이 기간 안에 있는 회원',
  metrics: [
    metric({
      key: 'activeUsers',
      label: '활성 사용자',
      count: 4,
      definition: '기간 안에 화면을 열었거나 AI에 질문한 사용자 수.',
    }),
    metric({
      key: 'onboarding',
      label: '온보딩 완료율',
      kind: 'ratio',
      count: null,
      numerator: 3,
      denominator: 3,
      sampleHidden: true,
    }),
    metric({
      key: 'nodeCtr',
      label: '노드 클릭률',
      kind: 'ratio',
      unit: '노출',
      count: null,
      numerator: 15,
      denominator: 37,
      rate: 0.405,
    }),
    metric({
      key: 'briefingRate',
      group: 'interest',
      label: '브리핑 조회율',
      kind: 'ratio',
      count: null,
      numerator: 0,
      denominator: 4,
      sampleHidden: true,
    }),
  ],
  trend: [
    {
      date: '2026-10-05',
      activeUsers: 2,
      nodeSelections: 9,
      edgeSelections: 1,
      briefingViews: 0,
      aiQuestions: 1,
    },
    {
      date: '2026-10-06',
      activeUsers: 4,
      nodeSelections: 30,
      edgeSelections: 1,
      briefingViews: 0,
      aiQuestions: 2,
    },
  ],
  rounds: [],
};

const company: InsightCompanyDetail = {
  window: '7d',
  asOf: '2026-10-06T03:44:13Z',
  companyId: 'samsung',
  name: '삼성전자',
  ticker: '005930',
  inCatalog: true,
  watchlistMembers: 2,
  holdingMembers: 1,
  nodeViews: 12,
  edgeSelections: 3,
  issueSelections: 4,
  aiQuestions: 1,
  viewers: 3,
  minSample: 5,
  series: [
    {
      date: '2026-10-06',
      nodeViews: 12,
      edgeSelections: 3,
      issueSelections: 4,
      aiQuestions: 1,
    },
  ],
  note: '개인을 알 수 있는 값은 보여 주지 않아요.',
};

const feedback: FeedbackSummary = {
  window: 'all',
  start: null,
  end: null,
  asOf: '2026-10-06T03:44:24Z',
  minSample: 5,
  features: [
    {
      feature: 'chatbot_answer',
      label: 'AI 챗봇 답변',
      up: 6,
      down: 2,
      total: 8,
      rate: 0.75,
      sampleHidden: false,
      days: [{ date: '2026-10-06', up: 6, down: 2, rate: 0.75 }],
    },
    {
      feature: 'briefing_round',
      label: '브리핑 회차',
      up: 1,
      down: 1,
      total: 2,
      rate: null,
      sampleHidden: true,
      days: [{ date: '2026-10-06', up: 1, down: 1, rate: null }],
    },
    {
      feature: 'briefing_issue',
      label: '브리핑 핵심 이슈',
      up: 0,
      down: 0,
      total: 0,
      rate: null,
      sampleHidden: true,
      days: [{ date: '2026-10-06', up: 0, down: 0, rate: null }],
    },
  ],
  unsupported: [
    {
      feature: 'news_summary',
      label: '뉴스 요약',
      reason: '뉴스 요약을 만드는 기능이 아직 없어 평가할 대상이 없습니다.',
    },
  ],
  basis: '현재 유효한 평가만 셉니다.',
};

const transcript: TranscriptDetail = {
  id: 'chat-1',
  user: 'u-7f3a',
  userKind: 'member',
  startedAt: '2026-10-06T01:00:00Z',
  messages: [
    {
      id: 'msg-1',
      seq: 1,
      at: '2026-10-06T01:00:05Z',
      question: '[이메일]로 알려 줄 수 있어?',
      answer: '삼성전자는 반도체 사건과 연결돼 있어요.',
      status: 'answered',
      reason: null,
      contextLabels: ['삼성전자'],
      citationCount: 2,
      feedback: { up: 0, down: 1, reasons: ['근거가 부족해요'] },
    },
  ],
  masking: { rules: ['이메일', '전화번호'], counts: { email: 1 } },
};

function openAdmin(path: string) {
  return renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [
          { path: '/admin/stats', element: <AdminStatsPage /> },
          {
            path: '/admin/stats/companies/:companyId',
            element: <AdminCompanyStatsPage />,
          },
          { path: '/admin/feedback', element: <AdminFeedbackPage /> },
          {
            path: '/admin/feedback/transcripts/:sessionId',
            element: <AdminTranscriptPage />,
          },
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

describe('A-ADM-02 이용 통계 (FS065)', () => {
  test('요약: 지표·산식·정의를 묶음별 표로 보여 주고, 표본이 작으면 비율을 숨긴다', async () => {
    server.on('GET', SUMMARY, () => json(summary));
    openAdmin('/admin/stats');

    const usage = await screen.findByRole('table', {
      name: '서비스 이용 지표',
    });
    expect(within(usage).getByText('활성 사용자')).toBeTruthy();
    expect(within(usage).getByText('4')).toBeTruthy();
    expect(
      within(usage).getByText(
        '기간 안에 화면을 열었거나 AI에 질문한 사용자 수.',
      ),
    ).toBeTruthy();
    expect(within(usage).getByText('40.5%')).toBeTruthy();
    expect(within(usage).getByText('15 / 37노출')).toBeTruthy();
    expect(
      within(usage).getByText('3 / 3명 (분모 5 미만이라 비율 숨김)'),
    ).toBeTruthy();
    expect(within(usage).getAllByText('표본 부족')).toHaveLength(1);

    const interest = screen.getByRole('table', { name: '브리핑 관심도 지표' });
    expect(within(interest).getByText('브리핑 조회율')).toBeTruthy();
    expect(screen.getByText('이 묶음에 제공하는 지표가 없어요.')).toBeTruthy();
    expect(
      screen.getByText('이 기간에 브리핑을 조회하거나 평가한 기록이 없어요.'),
    ).toBeTruthy();

    const trend = screen.getByRole('table', { name: '일별 이용 추이' });
    const rows = within(trend).getAllByRole('row');
    expect(within(rows[1]).getByText('2026-10-06')).toBeTruthy();
    expect(server.calls('GET', SUMMARY)[0].query.get('window')).toBe('7d');
  });

  test('기간을 바꾸면 그 기간으로 다시 조회하고 주소에 남긴다', async () => {
    server.on('GET', SUMMARY, () => json(summary));
    const { user, location } = openAdmin('/admin/stats');
    await screen.findByRole('table', { name: '서비스 이용 지표' });

    await user.click(screen.getByRole('button', { name: '30일' }));

    expect(location()).toBe('/admin/stats?window=30d');
    await waitFor(() =>
      expect(server.calls('GET', SUMMARY).at(-1)?.query.get('window')).toBe(
        '30d',
      ),
    );
    expect(
      screen.getByRole('button', { name: '30일' }).getAttribute('aria-pressed'),
    ).toBe('true');
  });

  test('종목 순위: 커서로 다음 쪽을 이어 붙이고 기업 상세로 간다', async () => {
    server.on('GET', COMPANIES, (request) =>
      request.query.get('cursor') === 'next-1'
        ? json({
            window: '7d',
            asOf: '2026-10-06T03:44:13Z',
            totalCompanies: 24,
            holdingsNote: '가상 보유는 연결한 가상 계좌 기준이에요.',
            items: [
              {
                companyId: 'sk-hynix',
                name: 'SK하이닉스',
                ticker: '000660',
                watchlistMembers: 1,
                holdingMembers: 0,
                nodeViews: 5,
                edgeSelections: 0,
                aiQuestions: 0,
              },
            ],
            nextCursor: null,
          })
        : json({
            window: '7d',
            asOf: '2026-10-06T03:44:13Z',
            totalCompanies: 24,
            holdingsNote: '가상 보유는 연결한 가상 계좌 기준이에요.',
            items: [
              {
                companyId: 'samsung',
                name: '삼성전자',
                ticker: '005930',
                watchlistMembers: 2,
                holdingMembers: 1,
                nodeViews: 12,
                edgeSelections: 3,
                aiQuestions: 1,
              },
            ],
            nextCursor: 'next-1',
          }),
    );
    server.on('GET', COMPANY, () => json(company));
    const { user, location } = openAdmin('/admin/stats?tab=companies');

    expect(await screen.findByRole('link', { name: '삼성전자' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '더 보기' }));
    expect(
      await screen.findByRole('link', { name: 'SK하이닉스' }),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: '더 보기' })).toBeNull();
    expect(server.calls('GET', COMPANIES).at(-1)?.query.get('cursor')).toBe(
      'next-1',
    );

    await user.click(screen.getByRole('link', { name: '삼성전자' }));
    expect(location()).toBe('/admin/stats/companies/samsung');
    expect(await screen.findByText('12회')).toBeTruthy();
    expect(screen.getByText('조회한 사용자 3명')).toBeTruthy();
    expect(
      screen.getByText('개인을 알 수 있는 값은 보여 주지 않아요.'),
    ).toBeTruthy();
  });

  test('종목 순위: 커서가 만료되면(INVALID_CURSOR) 첫 쪽부터 다시 읽는다', async () => {
    server.on('GET', COMPANIES, (request) =>
      request.query.get('cursor') === 'expired'
        ? apiError(422, 'INVALID_CURSOR')
        : json({
            window: '7d',
            asOf: '2026-10-06T03:44:13Z',
            totalCompanies: 24,
            holdingsNote: '가상 보유는 연결한 가상 계좌 기준이에요.',
            items: [
              {
                companyId: 'samsung',
                name: '삼성전자',
                ticker: '005930',
                watchlistMembers: 2,
                holdingMembers: 1,
                nodeViews: 12,
                edgeSelections: 3,
                aiQuestions: 1,
              },
            ],
            nextCursor: 'expired',
          }),
    );
    const { user } = openAdmin('/admin/stats?tab=companies');

    await screen.findByRole('link', { name: '삼성전자' });
    await user.click(screen.getByRole('button', { name: '더 보기' }));

    await waitFor(() =>
      expect(
        server
          .calls('GET', COMPANIES)
          .filter((call) => !call.query.has('cursor')).length,
      ).toBe(2),
    );
    expect(await screen.findByRole('link', { name: '삼성전자' })).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('기업 통계가 없으면(404) 빈 상태로 안내한다', async () => {
    server.on('GET', COMPANY, () => apiError(404, 'RESOURCE_NOT_FOUND'));
    openAdmin('/admin/stats/companies/unknown');

    expect(
      await screen.findByText(
        '이 기업의 통계가 없어요. 통계에 나타난 적 없는 기업이에요.',
      ),
    ).toBeTruthy();
  });

  test('조회에 실패하면 권한 안내와 다시 시도를 보여 준다', async () => {
    let attempts = 0;
    server.on('GET', SUMMARY, () => {
      attempts += 1;
      return attempts === 1 ? apiError(403, 'ACCESS_DENIED') : json(summary);
    });
    const { user } = openAdmin('/admin/stats');

    const alert = await screen.findByRole('alert');
    expect(
      within(alert).getByText(
        '이 화면을 볼 권한이 없어요. 관리자 권한을 확인해 주세요.',
      ),
    ).toBeTruthy();
    await user.click(within(alert).getByRole('button', { name: '다시 시도' }));
    expect(
      await screen.findByRole('table', { name: '서비스 이용 지표' }),
    ).toBeTruthy();
  });
});

describe('A-ADM-02b 선호도·대화록 (FS066-02·FS066-03)', () => {
  test('요약: 기본은 전체 기간이고, 평가 없음·표본 부족·비율을 구분한다', async () => {
    server.on('GET', FEEDBACK, () => json(feedback));
    openAdmin('/admin/feedback');

    const table = await screen.findByRole('table', {
      name: 'AI 기능별 좋아요·싫어요',
    });
    expect(within(table).getByText('75%')).toBeTruthy();
    expect(within(table).getByText('표본 부족(2/5)')).toBeTruthy();
    expect(within(table).getByText('평가 없음')).toBeTruthy();
    expect(
      screen.getByText(
        'ⓘ 뉴스 요약: 뉴스 요약을 만드는 기능이 아직 없어 평가할 대상이 없습니다.',
      ),
    ).toBeTruthy();
    const trend = screen.getByRole('table', { name: '일별 좋아요·싫어요' });
    expect(within(trend).getByText('6 / 2')).toBeTruthy();
    expect(screen.getByText(/기간 전체 보관 기간/)).toBeTruthy();
    expect(server.calls('GET', FEEDBACK)[0].query.get('window')).toBe('all');
  });

  test('직접 고른 날짜는 기간 대신 쓰고, 순서가 틀리면 막는다', async () => {
    server.on('GET', FEEDBACK, () => json(feedback));
    const { user, location } = openAdmin('/admin/feedback');
    await screen.findByRole('table', { name: 'AI 기능별 좋아요·싫어요' });

    await user.type(screen.getByLabelText('시작일(KST)'), '2026-10-06');
    await user.type(screen.getByLabelText('종료일(KST)'), '2026-10-01');
    expect(screen.getByText('시작일이 종료일보다 늦어요.')).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: '기간 적용' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    await user.clear(screen.getByLabelText('종료일(KST)'));
    await user.type(screen.getByLabelText('종료일(KST)'), '2026-10-07');
    await user.click(screen.getByRole('button', { name: '기간 적용' }));

    expect(location()).toBe('/admin/feedback?start=2026-10-06&end=2026-10-07');
    await waitFor(() => {
      const query = server.calls('GET', FEEDBACK).at(-1)?.query;
      expect(query?.get('start')).toBe('2026-10-06');
      expect(query?.get('window')).toBeNull();
    });
  });

  test('싫어요 사유: 가명 사용자와 사유를 보여 주고 챗봇 답변은 대화록으로 잇는다', async () => {
    server.on('GET', DISLIKES, () =>
      json({
        total: 2,
        nextCursor: null,
        items: [
          {
            at: '2026-10-06T01:00:10Z',
            feature: 'chatbot_answer',
            featureLabel: 'AI 챗봇 답변',
            targetId: 'msg-1',
            targetLabel: '[이메일]로 알려 줄 수 있어?',
            reason: '근거가 부족해요',
            voter: 'u-7f3a',
            sessionId: 'chat-1',
          },
          {
            at: '2026-10-06T00:00:00Z',
            feature: 'briefing_round',
            featureLabel: '브리핑 회차',
            targetId: 'round-1',
            targetLabel: '2026-10-06 출근',
            reason: null,
            voter: 'u-11aa',
            sessionId: null,
          },
        ],
      }),
    );
    openAdmin('/admin/feedback?tab=dislikes&purpose=품질 점검');

    const table = await screen.findByRole('table', { name: '싫어요 사유' });
    expect(within(table).getByText('근거가 부족해요')).toBeTruthy();
    expect(within(table).getByText('사유 없음')).toBeTruthy();
    expect(within(table).getByText('u-7f3a')).toBeTruthy();
    expect(
      within(table).getByRole('link', { name: '열람' }).getAttribute('href'),
    ).toBe(
      `/admin/feedback/transcripts/chat-1?purpose=${encodeURIComponent('품질 점검')}`,
    );
    expect(screen.getByText(/싫어요 2건/)).toBeTruthy();
  });

  test('대화록은 열람 목적을 입력하기 전에는 요청하지 않는다', async () => {
    server.on('GET', TRANSCRIPTS, () =>
      json({
        total: 1,
        nextCursor: null,
        items: [
          {
            id: 'chat-1',
            user: 'u-7f3a',
            userKind: 'member',
            startedAt: '2026-10-06T01:00:00Z',
            lastAt: '2026-10-06T01:00:05Z',
            messages: 1,
            preview: '[이메일]로 알려 줄 수 있어?',
            up: 0,
            down: 1,
          },
        ],
      }),
    );
    const { user, location } = openAdmin('/admin/feedback?tab=transcripts');

    expect(
      await screen.findByText('열람 목적을 입력하면 대화록 목록을 불러와요.'),
    ).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '대화록 열기' }));
    expect(screen.getByText('열람 목적을 입력해 주세요.')).toBeTruthy();
    expect(server.calls('GET', TRANSCRIPTS)).toHaveLength(0);

    await user.type(screen.getByLabelText('열람 목적'), '품질 점검');
    await user.click(screen.getByRole('button', { name: '대화록 열기' }));

    const table = await screen.findByRole('table', { name: 'AI 대화록' });
    expect(within(table).getByText('[이메일]로 알려 줄 수 있어?')).toBeTruthy();
    expect(within(table).getByText('회원')).toBeTruthy();
    const request = server.calls('GET', TRANSCRIPTS)[0];
    expect(request.query.get('purpose')).toBe('품질 점검');
    expect(request.query.get('only')).toBe('all');

    await user.click(
      screen.getByRole('button', { name: '싫어요가 있는 대화' }),
    );
    expect(location()).toContain('only=disliked');
    await waitFor(() =>
      expect(server.calls('GET', TRANSCRIPTS).at(-1)?.query.get('only')).toBe(
        'disliked',
      ),
    );
  });

  test('대화록 상세: 목적이 없으면 묻고, 가린 사본과 열람 기록 안내를 보여 준다', async () => {
    server.on('GET', TRANSCRIPT, () => json(transcript));
    const { user } = openAdmin('/admin/feedback/transcripts/chat-1');

    expect(await screen.findByLabelText('열람 목적')).toBeTruthy();
    expect(server.calls('GET', TRANSCRIPT)).toHaveLength(0);
    await user.type(screen.getByLabelText('열람 목적'), '품질 점검');
    await user.click(screen.getByRole('button', { name: '대화록 열기' }));

    expect(
      await screen.findByText('삼성전자는 반도체 사건과 연결돼 있어요.'),
    ).toBeTruthy();
    expect(
      screen.getByText(
        '개인정보를 가린 사본이에요. 저장된 원문은 바뀌지 않았고, 이 열람은 감사 로그에 남았어요.',
      ),
    ).toBeTruthy();
    expect(screen.getByText(/이 대화에서 가린 것: 이메일 1건/)).toBeTruthy();
    expect(screen.getByText('싫어요 사유: 근거가 부족해요')).toBeTruthy();
    expect(screen.getByText('답변함')).toBeTruthy();
    expect(server.calls('GET', TRANSCRIPT)[0].query.get('purpose')).toBe(
      '품질 점검',
    );
  });

  test('가리기나 열람 기록에 실패하면 대화록을 보여 주지 않는다', async () => {
    server.on('GET', TRANSCRIPT, () => apiError(503, 'MASKING_FAILED'));
    openAdmin('/admin/feedback/transcripts/chat-1?purpose=점검');

    expect(
      await screen.findByText(
        '개인정보를 가리지 못해 대화록을 보여 주지 않았어요',
      ),
    ).toBeTruthy();
    expect(screen.queryByText('질문 1')).toBeNull();
  });
});
