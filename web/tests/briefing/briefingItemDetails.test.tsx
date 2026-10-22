import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { getBriefingItemDetail } from '@/apis/briefing/briefing';
import BriefingIssueList from '@/components/briefing/BriefingIssueList';
import PublishedBriefing from '@/components/briefing/PublishedBriefing';
import { useAuthStore } from '@/stores/useAuthStore';
import type {
  BriefingItem,
  BriefingItemDetail,
  BriefingResponse,
} from '@/types/briefing';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';

const path = '/api/v1/briefings/:roundId/items/:eventId';
const roundId = 'brf-2026-10-08-evening';
const eventId = 'issue:fixed/1';
const knownFailures: BriefingResponse['metadata']['failures'] = [
  {
    section: 'dataWindow',
    code: 'RETROSPECTIVE_BODY',
    message: '당시 수집·동일 본문 버전을 입증하지 않습니다.',
    retryable: false,
    asOf: null,
  },
  {
    section: 'graphVersion',
    code: 'SOURCE_UNAVAILABLE',
    message: '운영 권한·공개 그래프 승인이 없는 localhost 시뮬레이션입니다.',
    retryable: false,
    asOf: null,
  },
  {
    section: 'items',
    code: 'ITEMS_WITHHELD',
    message: '검증을 통과하지 못한 항목은 보류했습니다.',
    retryable: false,
    asOf: null,
  },
  {
    section: 'marketVariables',
    code: 'RETROSPECTIVE_DAILY_SNAPSHOT',
    message: '회차 마감 이전 일별 지표를 나중에 조회했습니다.',
    retryable: false,
    asOf: null,
  },
];

// D-BRF-01·02 합성 fixture. 실제 기사나 시장 전망이 아니다.
const item: BriefingItem = {
  eventId,
  rank: 1,
  title: '합성 기업의 공급 계획 발표',
  eventTime: '2026-10-08',
  timePrecision: 'day',
  companies: [
    {
      id: 'KRX:000001',
      name: '합성 기업',
      role: '공급사',
      roleUnconfirmed: false,
      relationType: 'INVOLVES',
    },
  ],
  evidenceIds: ['evidence-1'],
  summary: {
    text: '회차 카드 문안',
    evidenceIds: ['evidence-1'],
    generatedAt: '2026-10-08T17:31:00+09:00',
    resultVersion: 'summary-fixed-v1',
  },
  reason: '합성 이슈의 선정 이유',
  evidenceCount: 1,
};

function detail(
  overrides: Partial<BriefingItemDetail> = {},
): BriefingItemDetail {
  const contextText =
    '📰 앞 문장입니다. 고정된 정확 인용입니다. 뒤 문장입니다.';
  const quote = '고정된 정확 인용입니다.';
  const localStart = Array.from(contextText.split(quote)[0]).length;
  return {
    roundId,
    eventId,
    title: item.title,
    summary: {
      text: '고정 상세 문안',
      evidenceIds: ['evidence-1'],
      generatedAt: '2026-10-08T17:31:00+09:00',
      resultVersion: 'summary-fixed-v1',
    },
    selectionReason: '편집자가 기록한 선정 이유',
    claims: [
      { type: 'fact', text: '발표가 있었다.', evidenceIds: ['evidence-1'] },
      {
        type: 'plan',
        text: '내년 공급할 계획이다.',
        evidenceIds: ['evidence-1'],
      },
      {
        type: 'outlook',
        text: '공급 확대가 예상된다.',
        evidenceIds: ['evidence-1'],
      },
    ],
    companies: item.companies,
    evidence: [
      {
        id: 'evidence-1',
        quote,
        documentId: 'article-fixed',
        documentVersion: 'article-version-fixed-7',
        title: '고정 출처 기사 제목',
        publisher: '합성 매체',
        url: 'https://example.com/fixed-article',
        publishedAt: '2026-10-08T10:00:00+09:00',
        quoteVerified: true,
        sourceKind: 'news',
        bodySha256: 'fixture-body-sha',
        bodyContext: {
          text: contextText,
          start: 120,
          end: 120 + Array.from(contextText).length,
          quoteStart: 120 + localStart,
          quoteEnd: 120 + localStart + Array.from(quote).length,
          offsetUnit: 'unicode_code_point',
        },
      },
    ],
    limitations: ['관측 자료로 주가 영향을 입증하지 않았습니다.'],
    metadata: {
      source: 'fixture-pinned-snapshot',
      asOf: '2026-10-08T17:30:00+09:00',
      graphVersion: 'graph-fixed-v1',
      requestId: 'request-fixed',
      partial: false,
      failures: [],
    },
    ...overrides,
  };
}

function listing(id = roundId, version = 'graph-fixed-v1') {
  return (
    <MemoryRouter>
      <BriefingIssueList items={[item]} roundId={id} graphVersion={version} />
    </MemoryRouter>
  );
}

function published(): BriefingResponse {
  return {
    id: roundId,
    date: '2026-10-08',
    edition: 'evening',
    status: 'published',
    scheduledAt: '2026-10-08T17:30:00+09:00',
    publishedAt: '2026-10-08T17:31:00+09:00',
    generatedAt: '2026-10-08T17:31:00+09:00',
    dataAsOf: '2026-10-08T17:30:00+09:00',
    graphVersion: 'graph-fixed-v1',
    items: [item],
    marketSummary: { status: 'unavailable', reason: '합성 시장 요약 없음' },
    marketVariables: { status: 'unavailable', reason: '합성 지표 없음' },
    sinceMorning: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: detail().metadata,
  };
}

beforeEach(() => useAuthStore.getState().clearSession());

describe('D-BRF-01·02 고정 상세·근거 보기', () => {
  it('발행 화면의 두 버튼이 펼칠 때만 한 번 조회하고 문안·선정이유·원문 맥락을 분리한다', async () => {
    const server = createFakeServer();
    const response = deferred<Response>();
    server.on('GET', '/api/v1/briefings', () => json(published()));
    server.on('GET', path, () => response.promise);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <PublishedBriefing date="2026-10-08" edition="evening" />
      </MemoryRouter>,
    );
    const detailButton = await screen.findByRole('button', {
      name: '핵심 이슈 1 자세히 보기',
    });
    const evidenceButton = screen.getByRole('button', {
      name: '핵심 이슈 1 근거 보기',
    });
    expect(server.calls('GET', path)).toHaveLength(0);
    expect(detailButton.getAttribute('aria-expanded')).toBe('false');

    await user.click(detailButton);
    expect(
      screen.getByText('이 회차의 상세·근거를 불러오고 있어요.'),
    ).toBeTruthy();
    await user.click(evidenceButton);
    expect(server.calls('GET', path)).toHaveLength(1);
    expect(server.calls('GET', path)[0].params).toEqual({ roundId, eventId });
    await act(async () =>
      response.resolve(
        json(
          detail({
            metadata: {
              ...detail().metadata,
              partial: true,
              failures: knownFailures,
            },
            limitations: [
              ...detail().limitations,
              ...knownFailures.map((failure) => failure.message),
            ],
          }),
        ),
      ),
    );

    const detailSection = screen.getByRole('region', {
      name: '핵심 이슈 1 상세',
    });
    const evidenceSection = screen.getByRole('region', {
      name: '핵심 이슈 1 근거',
    });
    for (const label of ['사실', '계획', '전망']) {
      expect(within(detailSection).getByText(label)).toBeTruthy();
    }
    expect(within(detailSection).getByText('고정 상세 문안')).toBeTruthy();
    expect(
      within(detailSection).getByText('편집자가 기록한 선정 이유'),
    ).toBeTruthy();
    expect(
      within(detailSection).getByText(/사건 관련 기업 · 공급사/),
    ).toBeTruthy();
    expect(
      within(detailSection).queryByText('고정된 정확 인용입니다.'),
    ).toBeNull();
    expect(
      within(evidenceSection).getByRole('heading', {
        name: '고정 출처 기사 제목',
      }),
    ).toBeTruthy();
    expect(
      within(evidenceSection).getByText(
        '합성 매체 · 발행 2026-10-08 10:00 KST',
      ),
    ).toBeTruthy();
    expect(evidenceSection.querySelector('blockquote')?.textContent).toBe(
      '고정된 정확 인용입니다.',
    );
    expect(evidenceSection.querySelector('mark')?.textContent).toBe(
      '고정된 정확 인용입니다.',
    );
    expect(
      within(evidenceSection).getByText(/📰 앞 문장입니다/).textContent,
    ).toBe(detail().evidence[0].bodyContext?.text);
    expect(
      within(evidenceSection).getByText('원문 버전 article-version-fixed-7'),
    ).toBeTruthy();
    const link = within(evidenceSection).getByRole('link', {
      name: /원문 보기/,
    });
    expect(link.getAttribute('href')).toBe('https://example.com/fixed-article');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(
      screen.getByRole('note', { name: '상세·근거 확인 범위' }).textContent,
    ).toContain('관측 자료로 주가 영향을 입증하지 않았습니다.');
    expect(
      screen.queryByText('일부 상세 정보를 제공하지 못했어요.'),
    ).toBeNull();
    for (const failure of knownFailures) {
      expect(screen.getAllByText(failure.message)).toHaveLength(1);
    }

    await user.click(detailButton);
    await user.click(evidenceButton);
    expect(detailButton.getAttribute('aria-expanded')).toBe('false');
    expect(
      screen.queryByRole('region', { name: '핵심 이슈 1 근거' }),
    ).toBeNull();
    server.on('GET', path, () => json(detail()));
    await user.click(evidenceButton);
    expect(server.calls('GET', path)).toHaveLength(2);
    const reopened = await screen.findByRole('region', {
      name: '핵심 이슈 1 근거',
    });
    expect(within(reopened).getByText('주변 본문')).toBeTruthy();
  });

  it('모두 닫은 뒤 재열면 권한을 재조회하고 503이면 이전 성공 문안을 숨긴다', async () => {
    const server = createFakeServer();
    server.on('GET', path, () => json(detail()));
    const user = userEvent.setup();
    render(listing());
    await user.click(
      screen.getByRole('button', { name: '핵심 이슈 1 자세히 보기' }),
    );
    expect(await screen.findByText('고정 상세 문안')).toBeTruthy();
    await user.click(
      screen.getByRole('button', { name: '핵심 이슈 1 자세히 접기' }),
    );

    const denied = deferred<Response>();
    server.on('GET', path, () => denied.promise);
    await user.click(
      screen.getByRole('button', { name: '핵심 이슈 1 자세히 보기' }),
    );
    expect(server.calls('GET', path)).toHaveLength(2);
    expect(screen.queryByText('고정 상세 문안')).toBeNull();
    await act(async () => denied.resolve(apiError(503, 'SOURCE_UNAVAILABLE')));
    expect((await screen.findByRole('alert')).textContent).toBe(
      '이 회차의 고정 상세·근거를 지금 제공할 수 없어요. 다시 시도해 주세요.',
    );
    expect(screen.queryByText('고정 상세 문안')).toBeNull();

    server.on('GET', path, () => json(detail()));
    await user.click(
      screen.getByRole('button', { name: '상세·근거 다시 시도' }),
    );
    expect(await screen.findByText('고정 상세 문안')).toBeTruthy();
    expect(server.calls('GET', path)).toHaveLength(3);
  });

  it.each([
    {
      label: '알려진 확인 범위만 있음',
      failures: knownFailures,
      title: '이 회차 자료의 확인 범위',
    },
    {
      label: '시장 지표 미제공',
      failures: knownFailures.map((failure) =>
        failure.section === 'marketVariables'
          ? { ...failure, code: 'SOURCE_UNAVAILABLE' }
          : failure,
      ),
      title: '일부 정보를 불러오지 못했어요.',
    },
    {
      label: '알 수 없는 장애',
      failures: [
        ...knownFailures,
        {
          section: 'unexpected',
          code: 'UNEXPECTED_MISSING',
          message: '확인하지 못한 정보가 있습니다.',
          retryable: true,
          asOf: null,
        },
      ],
      title: '일부 정보를 불러오지 못했어요.',
    },
  ])(
    '$label일 때 코드와 section에 맞는 안내를 유지한다',
    async ({ failures, title }) => {
      const server = createFakeServer();
      server.on('GET', '/api/v1/briefings', () =>
        json({
          ...published(),
          metadata: { ...detail().metadata, partial: true, failures },
        }),
      );
      render(
        <MemoryRouter>
          <PublishedBriefing date="2026-10-08" edition="evening" />
        </MemoryRouter>,
      );
      expect(await screen.findByText(title)).toBeTruthy();
      for (const failure of failures)
        expect(screen.getByText(failure.message)).toBeTruthy();
    },
  );

  it.each(['exa', 'tavily'])(
    '%s는 수집원으로 표시하고 안전한 원문 URL의 호스트만 출처에 덧붙인다',
    async (publisher) => {
      const server = createFakeServer();
      server.on('GET', path, () =>
        json(detail({ evidence: [{ ...detail().evidence[0], publisher }] })),
      );
      const user = userEvent.setup();
      render(listing());
      await user.click(
        screen.getByRole('button', { name: '핵심 이슈 1 근거 보기' }),
      );
      expect(
        await screen.findByText(
          `수집원 ${publisher} · 원문 example.com · 발행 2026-10-08 10:00 KST`,
        ),
      ).toBeTruthy();
      expect(
        screen.queryByText(`${publisher} · 발행 2026-10-08 10:00 KST`),
      ).toBeNull();
    },
  );

  it('문안의 근거 번호를 누르면 해당 고정 인용을 펼치고 키보드 초점을 옮긴다', async () => {
    const server = createFakeServer();
    server.on('GET', path, () => json(detail()));
    const user = userEvent.setup();
    render(listing());
    await user.click(
      screen.getByRole('button', { name: '핵심 이슈 1 자세히 보기' }),
    );
    const refs = await screen.findAllByRole('button', { name: '근거 1 확인' });
    await user.click(refs[0]);
    const evidenceCard = await screen.findByRole('article', {
      name: '근거 1: 고정 출처 기사 제목',
    });
    await waitFor(() => expect(document.activeElement).toBe(evidenceCard));
    await user.keyboard('{Escape}');
    const button = screen.getByRole('button', {
      name: '핵심 이슈 1 근거 보기',
    });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(button);
    expect(server.calls('GET', path)).toHaveLength(1);
  });

  it.each([
    [401, '이 회차의 상세·근거를 조회할 권한이 없어요.'],
    [403, '이 회차의 상세·근거를 조회할 권한이 없어요.'],
    [404, '이 회차에서 제공할 수 있는 상세·근거가 없어요.'],
    [
      503,
      '이 회차의 고정 상세·근거를 지금 제공할 수 없어요. 다시 시도해 주세요.',
    ],
  ])(
    'HTTP %s를 안내하고 같은 회차 상세 조회를 재시도한다',
    async (status, message) => {
      const server = createFakeServer();
      server.on('GET', path, () =>
        apiError(status as number, 'DETAIL_UNAVAILABLE'),
      );
      const user = userEvent.setup();
      render(listing());
      await user.click(
        screen.getByRole('button', { name: '핵심 이슈 1 근거 보기' }),
      );
      expect((await screen.findByRole('alert')).textContent).toBe(message);
      expect(screen.queryByRole('link', { name: /원문 보기/ })).toBeNull();
      server.on('GET', path, () => json(detail()));
      await user.click(
        screen.getByRole('button', { name: '상세·근거 다시 시도' }),
      );
      expect(
        await screen.findByRole('heading', { name: '고정 출처 기사 제목' }),
      ).toBeTruthy();
      expect(screen.queryByRole('alert')).toBeNull();
      expect(server.calls('GET', path)).toHaveLength(2);
    },
  );

  it.each(['roundId', 'eventId', 'graphVersion'] as const)(
    '다른 %s의 응답을 상세 화면에 쓰지 않는다',
    async (field) => {
      const server = createFakeServer();
      server.on('GET', path, () =>
        json(
          detail({
            ...(field === 'roundId' ? { roundId: 'other-round' } : {}),
            ...(field === 'eventId' ? { eventId: 'other-event' } : {}),
            ...(field === 'graphVersion'
              ? {
                  metadata: {
                    ...detail().metadata,
                    graphVersion: 'other-version',
                  },
                }
              : {}),
          }),
        ),
      );
      const user = userEvent.setup();
      render(listing());
      await user.click(
        screen.getByRole('button', { name: '핵심 이슈 1 자세히 보기' }),
      );
      expect((await screen.findByRole('alert')).textContent).toBe(
        '상세·근거를 불러오지 못했어요. 다시 시도해 주세요.',
      );
      expect(screen.queryByText('고정 상세 문안')).toBeNull();
    },
  );

  it('회차 전환 뒤 늦게 온 이전 상세를 버리고 새 회차를 다시 펼쳐 조회한다', async () => {
    const server = createFakeServer();
    const old = deferred<Response>();
    server.on('GET', path, (request) =>
      request.params.roundId === roundId
        ? old.promise
        : json(
            detail({
              roundId: 'next-round',
              summary: {
                status: 'unavailable',
                reason: '새 회차는 검증 문안 없음',
              },
            }),
          ),
    );
    const user = userEvent.setup();
    const view = render(listing());
    await user.click(
      screen.getByRole('button', { name: '핵심 이슈 1 자세히 보기' }),
    );
    view.rerender(listing('next-round'));
    await act(async () => old.resolve(json(detail())));
    expect(screen.queryByText('고정 상세 문안')).toBeNull();
    expect(
      screen
        .getByRole('button', { name: '핵심 이슈 1 자세히 보기' })
        .getAttribute('aria-expanded'),
    ).toBe('false');
    await user.click(
      screen.getByRole('button', { name: '핵심 이슈 1 자세히 보기' }),
    );
    expect(await screen.findByText('새 회차는 검증 문안 없음')).toBeTruthy();
    expect(server.calls('GET', path)).toHaveLength(2);
  });

  it('없는 주변본문·발행일·매체와 위험한 원문 URL을 임의로 채우지 않는다', async () => {
    const server = createFakeServer();
    server.on('GET', path, () =>
      json(
        detail({
          claims: [],
          companies: [],
          evidence: [
            {
              ...detail().evidence[0],
              bodyContext: null,
              publishedAt: null,
              publisher: '',
              url: 'javascript:alert(1)',
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    render(listing());
    await user.click(
      screen.getByRole('button', { name: '핵심 이슈 1 근거 보기' }),
    );
    expect(
      await screen.findByText('이 원문 버전의 주변 본문은 제공되지 않았어요.'),
    ).toBeTruthy();
    expect(screen.getByText('매체 미제공 · 발행 시각 미상')).toBeTruthy();
    expect(
      screen.getByText('사용할 수 있는 원문 URL이 제공되지 않았어요.'),
    ).toBeTruthy();
    expect(screen.queryByRole('link', { name: /원문 보기/ })).toBeNull();
    await user.click(
      screen.getByRole('button', { name: '핵심 이슈 1 자세히 보기' }),
    );
    expect(
      screen.getByText('문안의 사실·계획·전망 구분이 제공되지 않았어요.'),
    ).toBeTruthy();
    expect(screen.getByText('확인된 기업이 없어요.')).toBeTruthy();
  });

  it('공개 상세 조회는 round/event 경로를 인코딩한다', async () => {
    const server = createFakeServer();
    server.on('GET', path, () => json(detail()));
    await getBriefingItemDetail(roundId, eventId, 'graph-fixed-v1');
    expect(server.calls('GET', path)[0].path).toBe(
      `/api/v1/briefings/${roundId}/items/issue%3Afixed%2F1`,
    );
  });
});
