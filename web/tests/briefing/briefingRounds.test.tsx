import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import BriefingPage from '@/pages/briefing/BriefingPage';
import BriefingSnapshotBanner from '@/components/graph/BriefingSnapshotBanner';
import { getGraph, graphUrl } from '@/apis/graph/graph';
import { BriefingGraphUnavailableError } from '@/apis/graph/briefing-context';
import { createMockGraph } from '@/mocks/graph/response';
import type {
  BriefingGraphBasis,
  BriefingResponse,
  BriefingRoundRef,
} from '@/types/briefing';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';

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
  await expect(failure).rejects.toBeInstanceOf(BriefingGraphUnavailableError);
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
  server.on('GET', '/api/v1/briefings/:id/graph', () =>
    json({ ...basis(), keyIssueIds: [], companyIds: [] }),
  );
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

function briefing(
  date = '2026-09-17',
  edition: 'morning' | 'evening' = 'morning',
): BriefingResponse {
  return {
    id: `brf-${date}-${edition}`,
    date,
    edition,
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
    expect(where()).toBe('/briefing?date=2026-09-16&edition=morning');
    await waitFor(() =>
      expect(
        server.calls('GET', '/api/v1/briefings').at(-1)?.query.get('date'),
      ).toBe('2026-09-16'),
    );

    await user.selectOptions(select, '');
    expect(where()).toBe('/briefing?edition=morning');
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
    renderAt('/briefing?reading=full', <BriefingPage />);

    const link = await screen.findByRole('link', {
      name: '이 회차 전체 관계 그래프',
    });
    expect(link.getAttribute('href')).toBe('/?round=brf-2026-09-17-morning');
  });
});

// D-BRF-01/02: date and edition change together, using public history rather than invented availability.
const fourRounds = [
  ref('2026-10-23', 'morning'),
  ref('2026-10-22', 'evening'),
  ref('2026-10-22', 'morning'),
  ref('2026-10-21', 'evening'),
];
function roundLookup(server: ReturnType<typeof createFakeServer>) {
  server.on('GET', '/api/v1/briefings', (request) =>
    json(
      briefing(
        request.query.get('date') ?? '2026-10-23',
        request.query.get('edition') === 'evening' ? 'evening' : 'morning',
      ),
    ),
  );
}
function currentQuery() {
  return new URL(screen.getByTestId('where').textContent!, 'http://localhost')
    .searchParams;
}
function NavigateElsewhere() {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate('/briefing?date=2026-10-22&edition=evening')}
    >
      다른 회차로 이동
    </button>
  );
}

describe('D-BRF-01/02 available edition selection', () => {
  it('switches a morning preference to the only published evening atomically and preserves reading/view', async () => {
    const server = createFakeServer();
    roundLookup(server);
    server.on('GET', '/api/v1/briefings/rounds', () =>
      json({ items: fourRounds, nextCursor: null }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-23&edition=morning&reading=compact&view=personal',
      <BriefingPage />,
    );
    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect((select as HTMLSelectElement).disabled).toBe(false),
    );
    await user.selectOptions(select, '2026-10-21');
    expect(currentQuery().get('edition')).toBe('evening');
    expect(currentQuery().get('date')).toBe('2026-10-21');
    expect(currentQuery().get('reading')).toBe('compact');
    expect(currentQuery().get('view')).toBe('personal');
    await screen.findByRole('heading', { name: '퇴근 브리핑' });
    expect(
      (
        screen.getByRole('button', {
          name: '출근 · 미발행',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      screen.queryByText('출근 브리핑은 발행 이력이 없습니다.'),
    ).toBeNull();
    expect(
      server
        .calls('GET', '/api/v1/briefings')
        .filter(
          (r) =>
            r.query.get('date') === '2026-10-21' &&
            r.query.get('edition') === 'morning',
        ),
    ).toHaveLength(0);
  });
  it('retains an available preference when both exist and switches back for a morning-only day', async () => {
    const server = createFakeServer();
    roundLookup(server);
    server.on('GET', '/api/v1/briefings/rounds', () =>
      json({ items: fourRounds, nextCursor: null }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-21&edition=evening',
      <BriefingPage />,
    );
    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect((select as HTMLSelectElement).disabled).toBe(false),
    );
    await user.selectOptions(select, '2026-10-22');
    expect(currentQuery().get('edition')).toBe('evening');
    expect(
      (screen.getByRole('button', { name: '출근' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    expect(
      (screen.getByRole('button', { name: '퇴근' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    await user.selectOptions(select, '2026-10-23');
    expect(currentQuery().get('edition')).toBe('morning');
    expect(
      (
        screen.getByRole('button', {
          name: '퇴근 · 미발행',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    await user.selectOptions(select, '2026-10-22');
    expect(currentQuery().get('edition')).toBe('morning');
  });
  it('loads the rest of a split date before choosing or declaring an edition absent', async () => {
    const server = createFakeServer();
    roundLookup(server);
    const page = deferred<Response>();
    server.on('GET', '/api/v1/briefings/rounds', (r) =>
      r.query.get('cursor')
        ? page.promise
        : json({
            items: [fourRounds[0], fourRounds[3]],
            nextCursor: 'split-day',
          }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-23&edition=morning',
      <BriefingPage />,
    );
    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect((select as HTMLSelectElement).disabled).toBe(false),
    );
    await user.selectOptions(select, '2026-10-21');
    expect(
      server
        .calls('GET', '/api/v1/briefings')
        .filter((r) => r.query.get('date') === '2026-10-21'),
    ).toHaveLength(0);
    expect(
      screen.getByText('선택한 날짜의 발행 회차를 확인하고 있어요.'),
    ).toBeTruthy();
    await act(async () =>
      page.resolve(
        json({ items: [ref('2026-10-21', 'morning')], nextCursor: null }),
      ),
    );
    await waitFor(() => expect(currentQuery().get('date')).toBe('2026-10-21'));
    expect(currentQuery().get('edition')).toBe('morning');
    expect(
      (screen.getByRole('button', { name: '출근' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    expect(
      screen.queryByText('출근 브리핑은 발행 이력이 없습니다.'),
    ).toBeNull();
  });
  it('uses a known published edition after a page failure without calling the unknown one absent', async () => {
    const server = createFakeServer();
    roundLookup(server);
    server.on('GET', '/api/v1/briefings/rounds', (r) =>
      r.query.get('cursor')
        ? apiError(503, 'SOURCE_UNAVAILABLE')
        : json({
            items: [fourRounds[0], fourRounds[3]],
            nextCursor: 'split-day',
          }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-23&edition=morning',
      <BriefingPage />,
    );
    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect((select as HTMLSelectElement).disabled).toBe(false),
    );
    await user.selectOptions(select, '2026-10-21');
    await waitFor(() => expect(currentQuery().get('edition')).toBe('evening'));
    expect(
      screen.getByText(
        '회차 이력을 불러오지 못해 발행 여부를 확인할 수 없습니다.',
      ),
    ).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: '출근' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    expect(
      screen.queryByText('출근 브리핑은 발행 이력이 없습니다.'),
    ).toBeNull();
  });
  it('prefers publication over suspension but keeps the suspended round accessible', async () => {
    const server = createFakeServer();
    roundLookup(server);
    server.on('GET', '/api/v1/briefings/rounds', () =>
      json({
        items: [
          ref('2026-10-23', 'morning'),
          ref('2026-10-22', 'evening'),
          ref('2026-10-22', 'morning', 'suspended'),
        ],
        nextCursor: null,
      }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-23&edition=morning',
      <BriefingPage />,
    );
    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect((select as HTMLSelectElement).disabled).toBe(false),
    );
    await user.selectOptions(select, '2026-10-22');
    expect(currentQuery().get('edition')).toBe('evening');
    const stopped = screen.getByRole('button', {
      name: '출근 · 중단',
    }) as HTMLButtonElement;
    expect(stopped.disabled).toBe(false);
    expect(
      screen.getByText('출근 브리핑은 제공이 중단되었습니다.'),
    ).toBeTruthy();
    await user.click(stopped);
    expect(currentQuery().get('edition')).toBe('morning');
  });
  it('keeps an all-suspended day inspectable instead of labelling it unpublished', async () => {
    const server = createFakeServer();
    roundLookup(server);
    server.on('GET', '/api/v1/briefings/rounds', () =>
      json({
        items: [
          ref('2026-10-23', 'morning'),
          ref('2026-10-21', 'evening', 'suspended'),
        ],
        nextCursor: null,
      }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-23&edition=morning',
      <BriefingPage />,
    );
    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect((select as HTMLSelectElement).disabled).toBe(false),
    );
    await user.selectOptions(select, '2026-10-21');
    expect(currentQuery().get('edition')).toBe('evening');
    expect(
      screen.getByText(/퇴근 브리핑은 제공이 중단되었습니다/),
    ).toBeTruthy();
    expect(
      (
        screen.getByRole('button', {
          name: '퇴근 · 중단',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });
  it('treats a first-page failure as unknown and keeps manual date lookup available', async () => {
    const server = createFakeServer();
    roundLookup(server);
    server.on('GET', '/api/v1/briefings/rounds', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    renderAt('/briefing?date=2026-10-23&edition=morning', <BriefingPage />);
    const date = await screen.findByLabelText('날짜');
    fireEvent.change(date, { target: { value: '2026-10-21' } });
    expect(currentQuery().get('date')).toBe('2026-10-21');
    expect(currentQuery().get('edition')).toBe('morning');
    expect(screen.queryByText(/브리핑은 발행 이력이 없습니다/)).toBeNull();
    expect(
      (screen.getByRole('button', { name: '퇴근' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
  it('does not replace a newer navigation with the response of an older date selection', async () => {
    const server = createFakeServer();
    roundLookup(server);
    const page = deferred<Response>();
    server.on('GET', '/api/v1/briefings/rounds', (r) =>
      r.query.get('cursor')
        ? page.promise
        : json({ items: fourRounds, nextCursor: 'split-day' }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-23&edition=morning',
      <>
        <BriefingPage />
        <NavigateElsewhere />
      </>,
    );
    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect((select as HTMLSelectElement).disabled).toBe(false),
    );
    await user.selectOptions(select, '2026-10-21');
    await user.click(screen.getByRole('button', { name: '다른 회차로 이동' }));
    expect(currentQuery().get('date')).toBe('2026-10-22');
    await act(async () =>
      page.resolve(
        json({ items: [ref('2026-10-21', 'morning')], nextCursor: null }),
      ),
    );
    expect(currentQuery().get('date')).toBe('2026-10-22');
    expect(currentQuery().get('edition')).toBe('evening');
    expect((select as HTMLSelectElement).disabled).toBe(false);
  });
  it('keeps an absent edition disabled while unrelated older history is loading', async () => {
    const server = createFakeServer();
    roundLookup(server);
    const page = deferred<Response>();
    server.on('GET', '/api/v1/briefings/rounds', (r) =>
      r.query.get('cursor')
        ? page.promise
        : json({ items: fourRounds, nextCursor: 'older' }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-23&edition=morning',
      <BriefingPage />,
    );
    const absent = (await screen.findByRole('button', {
      name: '퇴근 · 미발행',
    })) as HTMLButtonElement;
    await user.click(screen.getByRole('button', { name: '이전 회차 더 보기' }));
    expect(absent.disabled).toBe(true);
    await act(async () =>
      page.resolve(
        json({ items: [ref('2026-10-20', 'evening')], nextCursor: null }),
      ),
    );
    expect(absent.disabled).toBe(true);
  });
  it('distinguishes a date with no public history from a failed history request', async () => {
    const server = createFakeServer();
    roundLookup(server);
    server.on('GET', '/api/v1/briefings/rounds', () =>
      json({ items: fourRounds, nextCursor: null }),
    );
    renderAt('/briefing?date=2026-10-24&edition=morning', <BriefingPage />);
    expect(
      (
        (await screen.findByRole('button', {
          name: '출근 · 미발행',
        })) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole('button', {
          name: '퇴근 · 미발행',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      screen.queryByText(
        '회차 이력을 불러오지 못해 발행 여부를 확인할 수 없습니다.',
      ),
    ).toBeNull();
  });
  it('resolves latest to a published edition on the newest day', async () => {
    const server = createFakeServer();
    roundLookup(server);
    server.on('GET', '/api/v1/briefings/rounds', () =>
      json({ items: fourRounds, nextCursor: null }),
    );
    const { user } = renderAt(
      '/briefing?date=2026-10-21&edition=evening&reading=full',
      <BriefingPage />,
    );
    const select = await screen.findByLabelText('발행일');
    await waitFor(() =>
      expect((select as HTMLSelectElement).disabled).toBe(false),
    );
    await user.selectOptions(select, '');
    expect(currentQuery().get('date')).toBeNull();
    expect(currentQuery().get('edition')).toBe('morning');
    expect(currentQuery().get('reading')).toBe('full');
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
        '발행 당시의 관계·근거 · 핵심 이슈 1개 · 브리핑에 기록된 기업 1개 · 데이터 기준 2026-09-17 18:10 KST · 버전 v1 · 정정 1건은 브리핑에서 확인',
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
