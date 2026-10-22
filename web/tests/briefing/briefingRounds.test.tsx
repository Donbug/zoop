import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import BriefingPage from '@/pages/briefing/BriefingPage';
import BriefingSnapshotBanner from '@/components/graph/BriefingSnapshotBanner';
import { getGraph, graphUrl } from '@/apis/graph/graph';
import { RoundGraphUnavailableError } from '@/apis/graph/round-graph-error';
import { createMockGraph } from '@/mocks/graph/response';
import type {
  BriefingGraphBasis,
  BriefingResponse,
  BriefingRoundRef,
} from '@/types/briefing';
import { apiError, createFakeServer, json } from '../support/fakeServer';

it('회차 기준 그래프를 아직 제공하지 않으면 미제공 오류로 알리고 지도를 조회하지 않는다', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings/:id/graph', () =>
    json(
      basis({
        status: 'unavailable',
        message: '발행 당시 고정 그래프 조회가 아직 연결되지 않았습니다.',
        dataAsOf: null,
        graphVersion: null,
      }),
    ),
  );
  const failure = getGraph({
    mode: 'all',
    personalFilter: 'all',
    round: 'brf-2026-09-17-evening',
  });
  await expect(failure).rejects.toBeInstanceOf(RoundGraphUnavailableError);
  await expect(failure).rejects.toThrow(
    '발행 당시 고정 그래프 조회가 아직 연결되지 않았습니다.',
  );
  expect(server.calls('GET', '/api/v1/graph')).toHaveLength(0);
});

it('회차 지도를 개발용 최신 mock으로 바꾸지 않고 회차 API를 조회한다', async () => {
  const server = createFakeServer();
  const request = {
    mode: 'all' as const,
    personalFilter: 'all' as const,
    round: 'brf-2026-09-17-evening',
  };
  server.on('GET', '/api/v1/briefings/:id/graph', () => json(basis()));
  server.on('GET', '/api/v1/graph', () => {
    const graph = createMockGraph(request);
    return json({
      ...graph,
      metadata: {
        ...graph.metadata,
        graphVersion: 'v1',
        asOf: basis().dataAsOf,
      },
    });
  });
  await getGraph(request);
  expect(server.calls('GET', '/api/v1/graph')).toHaveLength(1);
  expect(server.calls('GET', '/api/v1/graph')[0].query.get('round')).toBe(
    request.round,
  );
});

// 합성 fixture. 와이어프레임 D-BRF-01·04(2026-09-17)의 예시를 따른다.
const ref = (
  date: string,
  edition: 'morning' | 'evening',
  status: 'published' | 'suspended' = 'published',
): BriefingRoundRef => ({
  id: `brf-${date}-${edition}`,
  date,
  edition,
  status,
  publishedAt: `${date}T09:11:00Z`,
});

function briefing(date = '2026-09-17'): BriefingResponse {
  return {
    id: `brf-${date}-morning`,
    date,
    edition: 'morning',
    status: 'published',
    scheduledAt: `${date}T07:40:00+09:00`,
    publishedAt: `${date}T07:41:00+09:00`,
    generatedAt: `${date}T07:41:00+09:00`,
    dataAsOf: `${date}T07:40:00+09:00`,
    graphVersion: 'v1',
    marketSummary: { status: 'unavailable', reason: '합성 요약 없음' },
    marketVariables: { status: 'unavailable', reason: '합성 지표 없음' },
    items: [],
    sinceMorning: null,
    emptyReason: null,
    notice: null,
    corrections: [],
    metadata: {
      source: 'fixture',
      asOf: `${date}T07:40:00+09:00`,
      graphVersion: 'v1',
      requestId: 'r',
      partial: false,
      failures: [],
    },
  };
}

function basis(
  overrides: Partial<BriefingGraphBasis> = {},
): BriefingGraphBasis {
  return {
    roundId: 'brf-2026-09-17-evening',
    date: '2026-09-17',
    edition: 'evening',
    status: 'available',
    message: null,
    reason: null,
    publishedAt: '2026-09-17T18:11:00+09:00',
    dataAsOf: '2026-09-17T18:10:00+09:00',
    graphVersion: 'v1',
    keyIssueIds: ['ev-1'],
    companyIds: ['samsung'],
    correctionCount: 0,
    ...overrides,
  };
}

function Where() {
  const location = useLocation();
  return (
    <output data-testid="where">{`${location.pathname}${location.search}`}</output>
  );
}

function renderAt(url: string, element: React.ReactNode) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              {element}
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
  return {
    user: userEvent.setup(),
    where: () => screen.getByTestId('where').textContent,
  };
}

describe('D-BRF-01·02 회차 이력 (FS033·FS035, listBriefingRounds)', () => {
  it('발행 이력의 날짜만 고르게 하고, 고르면 그 날짜 회차를 요청한다', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings', (request) =>
      json(briefing(request.query.get('date') ?? '2026-09-17')),
    );
    server.on('GET', '/api/v1/briefings/rounds', (request) =>
      request.query.get('cursor') === 'next-1'
        ? json({ items: [ref('2026-09-15', 'evening')], nextCursor: null })
        : json({
            items: [
              ref('2026-09-17', 'evening'),
              ref('2026-09-17', 'morning'),
              ref('2026-09-16', 'morning', 'suspended'),
            ],
            nextCursor: 'next-1',
          }),
    );
    const { user, where } = renderAt('/briefing', <BriefingPage />);

    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect(within(select).getAllByRole('option')).toHaveLength(3),
    );
    const options = within(select)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(options).toEqual([
      '최신 회차',
      '2026-09-17 · 퇴근·출근',
      '2026-09-16 · 출근(중단)',
    ]);

    await user.click(screen.getByRole('button', { name: '이전 회차 더 보기' }));
    expect(
      await within(select).findByRole('option', { name: '2026-09-15 · 퇴근' }),
    ).toBeTruthy();
    expect(
      screen.queryByRole('button', { name: '이전 회차 더 보기' }),
    ).toBeNull();

    await user.selectOptions(select, '2026-09-16');
    expect(where()).toBe('/briefing?date=2026-09-16');
    await waitFor(() =>
      expect(
        server.calls('GET', '/api/v1/briefings').at(-1)?.query.get('date'),
      ).toBe('2026-09-16'),
    );

    await user.selectOptions(select, '');
    expect(where()).toBe('/briefing');
  });

  it('이력을 불러오지 못하면 날짜를 직접 고르는 입력으로 바꾼다', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings', () => json(briefing()));
    server.on('GET', '/api/v1/briefings/rounds', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    renderAt('/briefing', <BriefingPage />);

    expect(
      await screen.findByText(/회차 이력을 불러오지 못해 날짜를 직접 골라요/),
    ).toBeTruthy();
    expect(screen.getByLabelText('날짜').getAttribute('type')).toBe('date');
  });

  it('발행 회차에서 이 회차 기준 지도(D-BRF-04)로 간다', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings', () => json(briefing()));
    server.on('GET', '/api/v1/briefings/rounds', () =>
      json({ items: [], nextCursor: null }),
    );
    renderAt('/briefing', <BriefingPage />);

    const link = await screen.findByRole('link', {
      name: '이 회차 전체 관계 그래프',
    });
    expect(link.getAttribute('href')).toBe('/?round=brf-2026-09-17-morning');
  });
});

describe('D-BRF-04 회차 기준 지도 (FS032·FS035, getBriefingGraphBasis)', () => {
  it('회차 기준 시각을 밝히고, 현재 그래프·브리핑으로 돌아갈 수 있다', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings/:id/graph', () =>
      json(basis({ correctionCount: 1 })),
    );
    const { user, where } = renderAt(
      '/?round=brf-2026-09-17-evening&select=node:samsung',
      <BriefingSnapshotBanner roundId="brf-2026-09-17-evening" />,
    );

    expect(screen.getByText('2026-09-17 퇴근 브리핑 기준 그래프')).toBeTruthy();
    expect(
      await screen.findByText(
        '발행 당시의 관계·근거 · 데이터 기준 2026-09-17 18:10 KST · 정정 1건은 브리핑에서 확인',
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '브리핑으로' }).getAttribute('href'),
    ).toBe('/briefing?date=2026-09-17&edition=evening');
    expect(
      server.calls('GET', '/api/v1/briefings/:id/graph')[0].params.id,
    ).toBe('brf-2026-09-17-evening');

    await user.click(
      screen.getByRole('button', { name: '현재 그래프로 보기' }),
    );
    expect(where()).toBe('/');
  });

  it('제공 중단 회차는 안내와 사유를 보여 준다', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/briefings/:id/graph', () =>
      json(
        basis({
          status: 'suspended',
          message: '이 회차는 제공이 중단됐어요.',
          reason: '내용 확인 중',
          keyIssueIds: [],
          companyIds: [],
        }),
      ),
    );
    renderAt(
      '/?round=brf-2026-09-17-evening',
      <BriefingSnapshotBanner roundId="brf-2026-09-17-evening" />,
    );

    expect((await screen.findByRole('alert')).textContent).toBe(
      '이 회차는 제공이 중단됐어요. · 내용 확인 중',
    );
  });

  it('회차 기준을 확인하지 못하면 다시 확인할 수 있다', async () => {
    const server = createFakeServer();
    let attempts = 0;
    server.on('GET', '/api/v1/briefings/:id/graph', () => {
      attempts += 1;
      return attempts === 1
        ? apiError(503, 'SOURCE_UNAVAILABLE')
        : json(basis());
    });
    const { user } = renderAt(
      '/?round=brf-2026-09-17-evening',
      <BriefingSnapshotBanner roundId="brf-2026-09-17-evening" />,
    );

    expect((await screen.findByRole('alert')).textContent).toContain(
      '회차 기준을 확인하지 못했어요',
    );
    await user.click(screen.getByRole('button', { name: '다시 확인' }));
    expect(await screen.findByText(/발행 당시의 관계·근거/)).toBeTruthy();
  });

  it('지도 요청에 회차 id를 그대로 붙여 최신 그래프로 바꾸지 않는다', () => {
    const url = graphUrl({
      mode: 'all',
      personalFilter: 'all',
      round: 'brf-2026-09-17-evening',
    });
    expect(new URL(url, 'http://x').searchParams.get('round')).toBe(
      'brf-2026-09-17-evening',
    );
  });
});
