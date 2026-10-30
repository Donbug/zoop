import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import BriefingComparison from '@/components/briefing/BriefingComparison';
import PublishedBriefing from '@/components/briefing/PublishedBriefing';
import { useAuthStore } from '@/stores/useAuthStore';
import type { BriefingItem, BriefingResponse } from '@/types/briefing';
import { createFakeServer, json } from '../support/fakeServer';

// D-BRF-01·02: getBriefing에 이미 있는 회차 판단·문서 판정·기사 수·정정 위치를 합성 자료로 확인한다.
const sentiment = (articleId: string, companyId: string) => ({
  articleId,
  sentiment: {
    label: 'negative' as const,
    companyId,
    rationale: '합성 판정 근거',
    quotes: ['합성 원문 인용'],
    judgedAt: '2026-10-08T09:00:00+09:00',
    model: 'fixture-model',
    promptVersion: 'fixture-prompt',
  },
});

const item = (overrides: Partial<BriefingItem> = {}): BriefingItem => ({
  title: '합성 이슈 하나',
  eventId: 'event-1',
  eventTime: null,
  timePrecision: 'unknown',
  companies: [
    {
      id: 'company-a',
      name: '합성기업A',
      role: null,
      roleUnconfirmed: false,
      relationType: 'INVOLVES',
    },
  ],
  evidenceIds: ['evidence-1'],
  summary: { status: 'unavailable', reason: '합성 요약 없음' },
  rank: 1,
  reason: '합성 선정 이유',
  evidenceCount: 1,
  ...overrides,
});

function briefing(overrides: Partial<BriefingResponse> = {}): BriefingResponse {
  return {
    id: 'brf-2026-10-08-morning',
    date: '2026-10-08',
    edition: 'morning',
    status: 'published',
    scheduledAt: '2026-10-08T09:20:00+09:00',
    publishedAt: '2026-10-08T09:21:00+09:00',
    generatedAt: '2026-10-08T09:21:00+09:00',
    dataAsOf: '2026-10-08T09:20:00+09:00',
    graphVersion: 'fixed-v1',
    items: [
      item({
        sourceSupport: { articleCount: 4 },
        documentSentiments: [
          sentiment('article-1', 'company-a'),
          sentiment('article-1', 'company-a'),
        ],
      }),
      item({
        title: '합성 이슈 둘',
        eventId: 'event-2',
        rank: 2,
        sourceSupport: { articleCount: 0 },
      }),
      item({ title: '합성 이슈 셋', eventId: 'event-3', rank: 3 }),
    ],
    marketSummary: { status: 'unavailable', reason: '합성 시장 요약 없음' },
    marketVariables: { status: 'unavailable', reason: '합성 지표 없음' },
    sinceMorning: null,
    previousComparison: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'fixture',
      asOf: '2026-10-08T09:20:00+09:00',
      graphVersion: 'fixed-v1',
      requestId: 'fixture-request',
      partial: false,
      failures: [],
    },
    ...overrides,
  };
}

const outlook = {
  label: 'mixed' as const,
  rationale: '합성 회차 판단 근거',
  issueIds: ['event-2', 'event-4', 'event-missing'],
  judgedAt: '2026-10-08T09:20:00+09:00',
  model: 'fixture-model',
  promptVersion: 'fixture-prompt',
};

const correction = (
  id: number,
  eventId: string | null | undefined,
  corrected: string,
) => ({
  id,
  ...(eventId === undefined ? {} : { eventId }),
  original: `발행 원문 ${id}`,
  corrected,
  reason: `정정 사유 ${id}`,
  createdAt: '2026-10-08T10:05:00+09:00',
});

function setup(response = briefing(), compact = true) {
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings', () => json(response));
  render(
    <MemoryRouter>
      <PublishedBriefing
        date={response.date}
        edition={response.edition}
        compact={compact}
      />
    </MemoryRouter>,
  );
}

beforeEach(() => useAuthStore.getState().clearSession());
/** 간단히 보기 카드는 접혀 있으므로 펼친 뒤 확인한다. */
async function openIssues() {
  await screen.findAllByText(/합성 이슈 하나/);
  const user = userEvent.setup();
  for (const title of screen.queryAllByText(/^합성 이슈/)) {
    const summary = title.closest('summary');
    if (summary && !summary.parentElement!.hasAttribute('open'))
      await user.click(summary);
  }
}

describe.each([
  ['간단히 보기', true],
  ['전체 보기', false],
])('D-BRF-01 발행 필드 · %s', (_, compact) => {
  it('회차 판단이 null이면 영역을 그리지 않는다', async () => {
    setup(briefing({ outlook: null }), compact);
    await openIssues();
    expect(screen.queryByRole('region', { name: '회차 판단' })).toBeNull();
  });

  it('문서 판정이 빈 배열이면 판정 목록을 그리지 않는다', async () => {
    setup(
      briefing({
        items: [item({ documentSentiments: [] })],
      }),
      compact,
    );
    await openIssues();
    expect(screen.queryByText(/원문 판정/)).toBeNull();
  });

  it('기업 id가 없으면 이름을 글자로만 둔다', async () => {
    const [company] = item().companies;
    setup(
      briefing({ items: [item({ companies: [{ ...company, id: '' }] })] }),
      compact,
    );
    await openIssues();
    expect(screen.getAllByText('합성기업A').length).toBeGreaterThan(0);
    expect(screen.queryByRole('link', { name: '합성기업A' })).toBeNull();
  });

  it('문서 판정은 기업별로 한 번만 보이고, 기사 수는 sourceSupport가 있을 때만 0건까지 보인다', async () => {
    setup(briefing(), compact);
    await openIssues();
    expect(screen.getAllByText('합성기업A · 원문 판정')).toHaveLength(1);
    expect(screen.getByText(/보도 기사 4건/)).toBeTruthy();
    expect(screen.getByText(/보도 기사 0건/)).toBeTruthy();
    expect(screen.getAllByText(/보도 기사/)).toHaveLength(2);
  });

  it('기업 이름은 기업 상세로 이어진다', async () => {
    setup(briefing(), compact);
    await openIssues();
    const links = screen.getAllByRole('link', { name: '합성기업A' });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links)
      expect(link.getAttribute('href')).toBe('/companies/company-a');
  });

  it('이슈 정정은 그 이슈 아래에, 회차·화면 밖 정정은 정정 이력에 원문·시각과 함께 둔다', async () => {
    setup(
      briefing({
        corrections: [
          correction(1, 'event-1', '이슈 정정 내용'),
          correction(2, null, '회차 정정 내용'),
          correction(3, 'event-hidden', '화면 밖 정정 내용'),
          correction(4, undefined, '과거 응답 정정 내용'),
          correction(5, 'event-4', '네 번째 이슈 정정 내용'),
        ],
        items: [
          ...briefing().items,
          item({ title: '합성 이슈 넷', eventId: 'event-4', rank: 4 }),
        ],
      }),
      compact,
    );
    const issueList = await screen.findByRole('list', {
      name: '이 이슈의 정정',
    });
    expect(within(issueList).getByText(/이슈 정정 내용/)).toBeTruthy();
    expect(within(issueList).getByText(/발행 원문 1/)).toBeTruthy();
    expect(within(issueList).getByText(/정정 시각/)).toBeTruthy();

    const history = screen
      .getByRole('heading', { name: '정정 이력' })
      .closest('section')!;
    expect(
      within(history).queryByText(/^정정 내용: 이슈 정정 내용$/),
    ).toBeNull();
    for (const text of [
      /회차 정정 내용/,
      /화면 밖 정정 내용/,
      /과거 응답/,
      /네 번째 이슈 정정 내용/,
    ])
      expect(within(history).getByText(text)).toBeTruthy();
    expect(within(history).getByText(/발행 원문 2/)).toBeTruthy();
    expect(within(history).getAllByText(/정정 시각/)).toHaveLength(4);
  });

  it('응답 순서가 순위와 달라도 상위 3건 기준으로 이슈 정정을 붙인다', async () => {
    const [first, second] = briefing().items;
    setup(
      briefing({
        items: [
          item({ title: '합성 이슈 넷', eventId: 'event-4', rank: 4 }),
          second,
          item({ title: '합성 이슈 셋', eventId: 'event-3', rank: 3 }),
          first,
        ],
        corrections: [
          correction(1, 'event-4', '네 번째 이슈 정정 내용'),
          correction(2, 'event-3', '세 번째 이슈 정정 내용'),
        ],
      }),
      compact,
    );
    const issueList = await screen.findByRole('list', {
      name: '이 이슈의 정정',
    });
    expect(within(issueList).getByText(/세 번째 이슈 정정 내용/)).toBeTruthy();
    expect(screen.queryByText(/합성 이슈 넷/)).toBeNull();
    const history = screen
      .getByRole('heading', { name: '정정 이력' })
      .closest('section')!;
    expect(within(history).getByText(/네 번째 이슈 정정 내용/)).toBeTruthy();
  });

  it('공지에 시각이 있으면 함께 보이고 끝에 안내 문구가 붙는다', async () => {
    setup(
      briefing({
        notice: {
          kind: 'correction',
          message: '합성 공지',
          reason: '합성 공지 사유',
          at: '2026-10-08T10:00:00+09:00',
        },
      }),
      compact,
    );
    const notice = await screen.findByText(/합성 공지 사유/);
    expect(notice.textContent).toMatch(/10:00/);
    expect(
      screen.getByText('본 정보는 참고용이며 투자 권유가 아니에요.'),
    ).toBeTruthy();
  });
});

describe('D-BRF-01 회차 판단', () => {
  const withFourth = () =>
    briefing({
      outlook,
      items: [
        ...briefing().items,
        item({ title: '합성 이슈 넷', eventId: 'event-4', rank: 4 }),
      ],
    });

  it('전체 보기에서 화면에 있는 근거 이슈는 앵커로, 없는 이슈는 제목만 보인다', async () => {
    setup(withFourth(), false);
    const section = await screen.findByRole('region', { name: '회차 판단' });
    expect(within(section).getByText('혼재')).toBeTruthy();
    expect(within(section).getByText('합성 회차 판단 근거')).toBeTruthy();
    expect(within(section).getByText('주가 전망이 아니에요.')).toBeTruthy();
    const links = within(section).getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual(['합성 이슈 둘']);
    const anchor = links[0].getAttribute('href')!.slice(1);
    expect(document.getElementById(anchor)).toBeTruthy();
    expect(within(section).getByText('합성 이슈 넷').tagName).toBe('SPAN');
    expect(within(section).queryByText(/event-missing/)).toBeNull();
  });

  it('간단히 보기에는 회차 판단을 그리지 않는다', async () => {
    setup(withFourth(), true);
    await openIssues();
    expect(screen.queryByRole('region', { name: '회차 판단' })).toBeNull();
  });
});

describe('D-BRF-01 비교 이슈 지도 링크', () => {
  const since = {
    status: 'available' as const,
    morningRoundId: 'brf-2026-10-08-morning',
    morningPublishedAt: null,
    morningDataAsOf: '2026-10-08T00:20:00Z',
    items: [
      {
        title: '새 합성 이슈',
        eventId: 'event-new',
        eventTime: null,
        timePrecision: 'unknown' as const,
        reportedAt: null,
        companyNames: [],
        change: 'new' as const,
        rank: 1,
        morningRank: null,
        evidenceCount: 1,
        morningEvidenceCount: null,
      },
      {
        title: '빠진 합성 이슈',
        eventId: 'event-dropped',
        eventTime: null,
        timePrecision: 'unknown' as const,
        reportedAt: null,
        companyNames: [],
        change: 'dropped' as const,
        rank: null,
        morningRank: 1,
        evidenceCount: null,
        morningEvidenceCount: 1,
      },
    ],
  };

  it('이번 회차 이슈는 이번 회차 지도로, 빠진 이슈는 비교 회차 지도로 잇는다', () => {
    render(
      <MemoryRouter>
        <BriefingComparison
          since={since}
          roundDate="2026-10-08"
          graphRoundId="brf-2026-10-08-evening"
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole('link', { name: '새 합성 이슈' }).getAttribute('href'),
    ).toBe('/?round=brf-2026-10-08-evening&select=node%3Aevent-new');
    expect(
      screen.getByRole('link', { name: '빠진 합성 이슈' }).getAttribute('href'),
    ).toBe('/?round=brf-2026-10-08-morning&select=node%3Aevent-dropped');
  });

  it('지도 회차가 없으면(새 분석 회차) 제목을 링크로 만들지 않는다', () => {
    render(
      <MemoryRouter>
        <BriefingComparison since={since} roundDate="2026-10-08" />
      </MemoryRouter>,
    );
    expect(screen.getByText('새 합성 이슈').tagName).toBe('SPAN');
    expect(screen.queryByRole('link', { name: '새 합성 이슈' })).toBeNull();
  });
});
