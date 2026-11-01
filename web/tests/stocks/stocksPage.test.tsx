import { act, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import StocksPage from '@/pages/stocks/StocksPage';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Session } from '@/types/auth';
import {
  companyListBody,
  NVIDIA,
  SAMSUNG,
  SAMSUNG_SDI,
  settingsBody,
} from '../support/fixtures';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { myMember } from '../support/myMember';
import { renderRoutes } from '../support/renderRoutes';

const COMPANIES = '/api/v1/companies';
const QUOTE = '/api/v1/companies/:id/quote';
const WATCH = '/api/v1/me/watchlist/:id';

const anonymous: Session = {
  authenticated: false,
  kind: 'anonymous',
  user: null,
  setup: null,
  csrfToken: null,
  expiresAt: null,
};

function member(): Session {
  return {
    authenticated: true,
    kind: 'member',
    user: {
      id: 'mem-1',
      email: 'member@zoop.test',
      displayName: '테스트 회원',
    },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: 'csrf-test',
    expiresAt: null,
  };
}

/** 시세: 삼성전자는 하락, 삼성SDI는 상승, NVIDIA는 시세 없음(정상 자료 부재) */
function quotes(server: FakeServer) {
  server.on('GET', QUOTE, ({ params }) => {
    if (params.id === SAMSUNG.id)
      return json({
        status: 'available',
        companyId: params.id,
        source: { name: 'synthetic' },
        quote: { currency: 'KRW', price: 271500, changeRate: -0.0163 },
      });
    if (params.id === SAMSUNG_SDI.id)
      return json({
        status: 'available',
        companyId: params.id,
        source: { name: 'synthetic' },
        quote: { currency: 'KRW', price: 567000, changeRate: 0.0718 },
      });
    return json({
      status: 'unavailable',
      companyId: params.id,
      reasonCode: 'no_data',
    });
  });
}

function openStocks(path = '/stocks') {
  return renderRoutes(
    [
      { path: '/stocks', element: <StocksPage /> },
      { path: '/login', element: <p>로그인 화면</p> },
    ],
    path,
  );
}

const list = () => screen.findByRole('list', { name: '종목 목록' });

test('D-STK-01: personal filter resets after switching member while preserving search and scope', async () => {
  useAuthStore.getState().setSession(member());
  const server = createFakeServer();
  myMember(server, { connected: true, watchlistIds: [NVIDIA.id] });
  quotes(server);
  const { user, location } = openStocks('/stocks?scope=mine&q=NVIDIA');
  await user.click(await screen.findByRole('button', { name: '관심 1' }));
  const next = member();
  if (next.user) next.user.id = 'mem-2';
  myMember(server, { connected: false, watchlistIds: [] });
  act(() => useAuthStore.getState().setSession(next));
  expect(sessionStorage.getItem('zoop.stocks.personal-filter')).toBeNull();
  expect(screen.queryByRole('list', { name: '종목 목록' })).toBeNull();
  expect(
    (await screen.findByRole('button', { name: '전체 0' })).getAttribute(
      'aria-pressed',
    ),
  ).toBe('true');
  expect(
    new URL(location(), 'http://localhost').searchParams.has('personal'),
  ).toBe(false);
  expect(new URL(location(), 'http://localhost').searchParams.get('q')).toBe(
    'NVIDIA',
  );
  expect(
    new URL(location(), 'http://localhost').searchParams.get('scope'),
  ).toBe('mine');
});

test('D-STK-01: restoring or rechecking the same member keeps the requested personal filter', async () => {
  useAuthStore.getState().setSession(member());
  const server = createFakeServer();
  myMember(server, { connected: true, watchlistIds: [NVIDIA.id] });
  quotes(server);
  const { location } = openStocks('/stocks?scope=mine&personal=watch');
  await screen.findByRole('button', { name: '관심 1' });
  act(() => useAuthStore.getState().setStatus('checking'));
  act(() => useAuthStore.getState().setSession(member()));
  await waitFor(() =>
    expect(
      screen
        .getByRole('button', { name: '관심 1' })
        .getAttribute('aria-pressed'),
    ).toBe('true'),
  );
  expect(location()).toContain('personal=watch');
});

test('D-STK-01: signing out resets the URL filter before the next member signs in', async () => {
  useAuthStore.getState().setSession(member());
  const server = createFakeServer();
  myMember(server, { connected: true, watchlistIds: [NVIDIA.id] });
  quotes(server);
  const { user, location } = openStocks('/stocks?scope=mine');
  await user.click(await screen.findByRole('button', { name: '관심 1' }));
  act(() => useAuthStore.getState().clearSession());
  expect(
    new URL(location(), 'http://localhost').searchParams.has('personal'),
  ).toBe(false);
  act(() => useAuthStore.getState().setSession(member()));
  await waitFor(() =>
    expect(
      screen
        .getByRole('button', { name: /^전체 / })
        .getAttribute('aria-pressed'),
    ).toBe('true'),
  );
});

test.each(['success', 'failure'])(
  'D-STK-01: late prior-member watch %s cannot restore rows or errors for the next member',
  async (result) => {
    useAuthStore.getState().setSession(member());
    const server = createFakeServer();
    myMember(server, { connected: true, watchlistIds: [NVIDIA.id] });
    quotes(server);
    const pending = deferred<Response>();
    server.on('PUT', WATCH, () => pending.promise);
    const { user } = openStocks('/stocks?scope=mine');
    await user.click(await screen.findByRole('button', { name: '관심 1' }));
    await user.click(
      within(await rowOf('NVIDIA')).getByRole('button', {
        name: 'NVIDIA 관심 종목',
      }),
    );
    myMember(server, { connected: false, watchlistIds: [] });
    const next = member();
    if (next.user) next.user.id = 'mem-next';
    act(() => useAuthStore.getState().setSession(next));
    await screen.findByRole('button', { name: '전체 0' });
    await act(async () =>
      pending.resolve(
        result === 'success'
          ? json(settingsBody({ watchlistIds: [SAMSUNG.id] }))
          : apiError(503, 'SOURCE_UNAVAILABLE'),
      ),
    );
    expect(
      screen
        .getByRole('button', { name: '전체 0' })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    expect(screen.queryByRole('list', { name: '종목 목록' })).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  },
);
const rowOf = async (name: string) =>
  (await within(await list()).findByText(name)).closest('li') as HTMLElement;

beforeEach(() => {
  sessionStorage.removeItem('zoop.stocks.personal-filter');
  useAuthStore.getState().setSession(anonymous);
});

describe('D-STK-01 종목 목록·검색 (FS037)', () => {
  test('들어오면 전체 종목과 개수, 최신 시세(등락률·시세 없음)를 보여 준다', async () => {
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    openStocks();

    expect(await screen.findByText('3개 종목')).toBeTruthy();
    expect(server.calls('GET', COMPANIES)[0].query.get('q')).toBe('');

    const samsung = await rowOf('삼성전자');
    expect(within(samsung).getByText('005930 · 승인 사건 27건')).toBeTruthy();
    expect(await within(samsung).findByText('271,500원')).toBeTruthy();
    expect(within(samsung).getByText('▼ -1.63%')).toBeTruthy();
    expect(
      await within(await rowOf('삼성SDI')).findByText('▲ +7.18%'),
    ).toBeTruthy();
    expect(await within(await rowOf('NVIDIA')).findByText('-')).toBeTruthy();
  });

  test('검색은 [검색]·Enter로만 하고, 검색어를 주소에 남긴다', async () => {
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    const { user, location } = openStocks();
    await list();

    const box = screen.getByLabelText('기업명·영문명·티커 검색');
    await user.type(box, '삼성');
    expect(server.calls('GET', COMPANIES)).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: '검색' }));
    await waitFor(() =>
      expect(location()).toBe('/stocks?q=%EC%82%BC%EC%84%B1'),
    );
    expect(await screen.findByText('2개 종목')).toBeTruthy();
    expect(screen.queryByText('NVIDIA')).toBeNull();

    await user.click(screen.getByRole('button', { name: '검색어 지우기' }));
    expect((box as HTMLInputElement).value).toBe('');
  });

  test('주소의 검색어로 들어오면 입력칸과 결과를 되살린다', async () => {
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    openStocks('/stocks?q=NVIDIA');

    expect(await screen.findByText('1개 종목')).toBeTruthy();
    expect(
      (screen.getByLabelText('기업명·영문명·티커 검색') as HTMLInputElement)
        .value,
    ).toBe('NVIDIA');
  });

  test('결과가 없으면 안내하고, 조회에 실패하면 다시 시도한다', async () => {
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    server.on('GET', COMPANIES, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = openStocks('/stocks?q=없는회사');

    expect((await screen.findByRole('alert')).textContent).toContain(
      '종목을 불러오지 못했어요',
    );

    server.on('GET', COMPANIES, () => json(companyListBody([])));
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(
      await screen.findByText("'없는회사' 검색 결과가 없어요."),
    ).toBeTruthy();
  });

  test('다음 페이지가 있으면 [더 보기]로 이어 붙이고, 실패하면 다시 시도한다', async () => {
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    let failNext = true;
    server.on('GET', COMPANIES, ({ query }) => {
      if (!query.get('cursor'))
        return json({ ...companyListBody([SAMSUNG]), nextCursor: 'page-2' });
      if (failNext) {
        failNext = false;
        return apiError(503, 'SOURCE_UNAVAILABLE');
      }
      return json(companyListBody([NVIDIA]));
    });
    const { user } = openStocks();

    expect(await screen.findByText('1개 종목')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '더 보기' }));
    expect((await screen.findByRole('alert')).textContent).toContain(
      '다음 종목을 불러오지 못했어요',
    );

    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('2개 종목')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '더 보기' })).toBeNull();
    expect(server.calls('GET', COMPANIES).at(-1)?.query.get('cursor')).toBe(
      'page-2',
    );
  });

  test('행에서 기업 상세와 지도(기업 선택)로 이동할 수 있다', async () => {
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    openStocks();

    const row = await rowOf('삼성전자');
    expect(
      within(row).getByRole('link', { name: '삼성전자' }).getAttribute('href'),
    ).toBe('/companies/cmp-samsung');
    expect(
      within(row)
        .getByRole('link', { name: '삼성전자 기업 상세' })
        .getAttribute('href'),
    ).toBe('/companies/cmp-samsung');
    expect(
      within(row)
        .getByRole('link', { name: '삼성전자 지도에서 보기' })
        .getAttribute('href'),
    ).toBe('/?select=node:cmp-samsung');
  });
});

describe('D-STK-01 관심 종목 (FS027)', () => {
  test('비회원이 ☆를 누르면 저장하지 않고 로그인을 안내한다', async () => {
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    const { user } = openStocks();

    await user.click(
      within(await rowOf('NVIDIA')).getByRole('button', {
        name: 'NVIDIA 관심 종목',
      }),
    );
    expect((await screen.findByRole('alert')).textContent).toContain(
      '로그인하면 관심 종목을 저장할 수 있어요',
    );
    expect(server.calls('PUT', WATCH)).toHaveLength(0);
  });

  test('회원은 ☆로 바로 저장하고, 실패하면 되돌린 뒤 다시 시도한다', async () => {
    useAuthStore.getState().setSession(member());
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    server.on('PUT', WATCH, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = openStocks();

    const star = () => screen.getByRole('button', { name: 'NVIDIA 관심 종목' });
    await rowOf('NVIDIA');
    await waitFor(() => expect(star().hasAttribute('disabled')).toBe(false));
    await user.click(star());

    expect((await screen.findByRole('alert')).textContent).toContain(
      '관심 종목을 저장하지 못했어요',
    );
    expect(star().getAttribute('aria-pressed')).toBe('false');

    myMember(server);
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    await waitFor(() =>
      expect(star().getAttribute('aria-pressed')).toBe('true'),
    );
    const puts = server.calls('PUT', WATCH);
    expect(puts).toHaveLength(2);
    expect(puts[1].body).toEqual({ watched: true });
  });

  test('[내 종목]은 보유·관심 종목만, 보유 배지와 함께 보여 준다', async () => {
    useAuthStore.getState().setSession(member());
    const server = createFakeServer();
    myMember(server, { connected: true, watchlistIds: [NVIDIA.id] });
    quotes(server);
    const { user, location } = openStocks();

    await list();
    await user.click(screen.getByRole('button', { name: '내 종목' }));
    expect(location()).toBe('/stocks?scope=mine');

    const names = async () =>
      within(await list())
        .getAllByRole('listitem')
        .map(
          (item) => item.querySelector('a[href^="/companies/"]')?.textContent,
        );
    await waitFor(async () =>
      expect(await names()).toEqual(['NVIDIA', '삼성전자']),
    );
    expect(within(await rowOf('삼성전자')).getByText('보유')).toBeTruthy();
    expect(
      within(await rowOf('NVIDIA'))
        .getByRole('button', { name: 'NVIDIA 관심 종목' })
        .getAttribute('aria-pressed'),
    ).toBe('true');
  });

  test('내 종목 필터와 개수를 유지하고 관심 해제 시 검색창에 초점을 옮긴다', async () => {
    useAuthStore.getState().setSession(member());
    const server = createFakeServer();
    myMember(server, { connected: true, watchlistIds: [NVIDIA.id] });
    quotes(server);
    const { user, location } = openStocks('/stocks?scope=mine');
    await screen.findByRole('button', { name: '관심 1' });
    await user.click(screen.getByRole('button', { name: '관심 1' }));
    expect(location()).toContain('personal=watch');
    expect(sessionStorage.getItem('zoop.stocks.personal-filter')).toBe('watch');
    expect(screen.getByText('NVIDIA')).toBeTruthy();
    expect(screen.queryByText('삼성전자')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'NVIDIA 관심 종목' }));
    expect(document.activeElement).toBe(
      screen.getByLabelText('기업명·영문명·티커 검색'),
    );
  });

  test('내 종목의 기업 정보 조회가 실패하면 빈 목록 대신 오류와 재시도를 제공한다', async () => {
    useAuthStore.getState().setSession(member());
    const server = createFakeServer();
    myMember(server, { watchlistIds: [NVIDIA.id] });
    quotes(server);
    server.on('GET', COMPANIES, () => json(companyListBody([SAMSUNG])));
    server.on('GET', '/api/v1/companies/:id', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    const { user } = openStocks('/stocks?scope=mine');

    expect((await screen.findByRole('alert')).textContent).toContain(
      '일부 종목 정보를 불러오지 못했어요',
    );
    expect(screen.queryByText('보유·관심 종목이 없어요.')).toBeNull();

    server.on('GET', '/api/v1/companies/:id', () =>
      json({
        ...NVIDIA,
        directIssues: [],
        structuralIssues: [],
      }),
    );
    await user.click(screen.getByRole('button', { name: '다시 시도' }));

    expect(await screen.findByText('NVIDIA')).toBeTruthy();
    expect(server.calls('GET', '/api/v1/companies/:id')).toHaveLength(2);
  });

  test('비회원은 [내 종목]에서 로그인 안내를 본다', async () => {
    const server = createFakeServer();
    myMember(server);
    quotes(server);
    openStocks('/stocks?scope=mine');

    expect(
      await screen.findByText(/로그인하면 보유·관심 종목만 모아 볼 수 있어요/),
    ).toBeTruthy();
    expect(screen.queryByRole('list', { name: '종목 목록' })).toBeNull();
  });
});
