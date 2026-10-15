import { screen, waitFor, within } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';
import {
  beforeEach,
  describe,
  expect,
  test,
  vi,
  type MockInstance,
} from 'vitest';
import MyStocksPage from '@/pages/my/MyStocksPage';
import { apiError, createFakeServer } from '../support/fakeServer';
import { myMember } from '../support/myMember';
import { renderRoutes } from '../support/renderRoutes';

const DELETE_CONNECTION = '/api/v1/portfolio/connections/:id';

function openMy(path = '/my') {
  return renderRoutes([{ path: '/my', element: <MyStocksPage /> }], path);
}

const holdingsSection = () =>
  screen.findByRole('region', { name: '보유 종목(가상 계좌)' });

const searchBox = async () =>
  within(
    await screen.findByRole('search', { name: '관심 종목 추가' }),
  ).getByRole('searchbox') as HTMLInputElement;

async function searchFor(user: UserEvent, term: string) {
  const box = await searchBox();
  await user.clear(box);
  await user.type(box, `${term}{Enter}`);
}

function setScrollY(value: number) {
  Object.defineProperty(window, 'scrollY', { value, configurable: true });
}

let scrollTo: MockInstance;

beforeEach(() => {
  // jsdom은 스크롤을 구현하지 않으므로 호출만 기록한다.
  scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  setScrollY(0);
});

describe('D-MY-01 / 01b 내 종목: 보유 종목과 계좌 연결', () => {
  test("미연결이면 머리글에 '연결 안 됨'과 점선 안내, [가상 계좌 연결하기]를 보여 준다", async () => {
    const server = createFakeServer();
    myMember(server);
    openMy();

    const section = await holdingsSection();
    expect(await within(section).findByText('연결 안 됨')).toBeTruthy();
    expect(
      within(section).getByText(
        '가상 계좌를 연결하면 모의 보유 종목과 평가 금액을 볼 수 있어요.',
      ),
    ).toBeTruthy();
    expect(
      within(section).getByText(
        '실제 증권 계좌가 아니에요. 준비된 모의 데이터로 만든 계좌예요.',
      ),
    ).toBeTruthy();
    expect(
      within(section).getByRole('button', { name: '가상 계좌 연결하기' }),
    ).toBeTruthy();
    expect(
      within(section).queryByRole('button', { name: '연결 끊기' }),
    ).toBeNull();
  });

  test('연결되면 보유 종목 수·[연결 끊기]·계좌 정보와 지도·상세로 가는 행을 보여 준다', async () => {
    const server = createFakeServer();
    myMember(server, { connected: true });
    openMy();

    const section = await holdingsSection();
    const list = await within(section).findByRole('list', {
      name: '보유 종목 목록',
    });
    expect(within(section).getByText('1개')).toBeTruthy();
    expect(
      within(section).getByRole('button', { name: '연결 끊기' }),
    ).toBeTruthy();
    expect(section.textContent).toContain(
      '모의 계좌 MOCK-0002 · 예수금 3,000,000원 · 모의 정보 기준 2026-10-01 20:33 KST · 평가 계산 2026-10-06 12:41 KST',
    );
    expect(section.textContent).toContain(
      '보유 종목의 시세 통화가 서로 달라요.',
    );
    expect(list.textContent).toContain(
      '005930 · 20주 · 평가 5,430,000원 · 비중 계산 불가',
    );
    expect(
      within(list)
        .getByRole('link', { name: '삼성전자, 지도에서 보기' })
        .getAttribute('href'),
    ).toBe('/?mode=personal&select=node:cmp-samsung');
    expect(
      within(list)
        .getByRole('link', { name: '삼성전자 기업 상세' })
        .getAttribute('href'),
    ).toBe('/companies/cmp-samsung');
  });

  test('연결하기는 내 종목 안에서 연결 기능을 열고, 연결하면 돌아와 보유 종목을 보여 준다', async () => {
    const server = createFakeServer();
    myMember(server);
    const { user, location } = openMy();

    await user.click(
      await screen.findByRole('button', { name: '가상 계좌 연결하기' }),
    );

    expect(location()).toBe('/my?account=connect');
    expect(
      await screen.findByRole('heading', { name: '가상 계좌를 연결해요' }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        '연결한 계좌의 모의 보유 종목이 내 종목에 보여요. 연결하거나 취소하면 내 종목으로 돌아가요.',
      ),
    ).toBeTruthy();
    expect(screen.queryByRole('heading', { name: '내 종목' })).toBeNull();

    await screen.findByRole('list', { name: '가상 계좌 목록' });
    await user.click(
      screen.getByRole('button', { name: '선택한 가상 계좌 연결하기' }),
    );

    await waitFor(() => expect(location()).toBe('/my'));
    const section = await holdingsSection();
    expect(
      await within(section).findByRole('list', { name: '보유 종목 목록' }),
    ).toBeTruthy();
    expect(within(section).getByText('삼성전자')).toBeTruthy();
  });

  test('[취소]로 돌아오면 연결하지 않고 검색어·검색 결과·스크롤 위치를 되살린다', async () => {
    const server = createFakeServer();
    myMember(server);
    const { user, location } = openMy();

    await searchFor(user, '삼성');
    await screen.findByRole('list', { name: '‘삼성’ 검색 결과' });
    setScrollY(640);
    await user.click(
      screen.getByRole('button', { name: '가상 계좌 연결하기' }),
    );
    await user.click(await screen.findByRole('button', { name: '취소' }));

    await waitFor(() => expect(location()).toBe('/my'));
    expect((await searchBox()).value).toBe('삼성');
    expect(screen.getByRole('list', { name: '‘삼성’ 검색 결과' })).toBeTruthy();
    expect(scrollTo).toHaveBeenLastCalledWith(0, 640);
    expect(server.calls('POST', '/api/v1/portfolio/connections')).toHaveLength(
      0,
    );
    // 목록을 다시 그리지 않았으므로 검색을 다시 요청하지 않는다.
    expect(server.calls('GET', '/api/v1/companies')).toHaveLength(1);
  });

  test('브라우저 뒤로 가기로 돌아와도 검색어를 되살린다', async () => {
    const server = createFakeServer();
    myMember(server);
    const { user, router, location } = openMy();

    await searchFor(user, 'NVDA');
    await user.click(
      screen.getByRole('button', { name: '가상 계좌 연결하기' }),
    );
    await screen.findByRole('heading', { name: '가상 계좌를 연결해요' });

    await router.navigate(-1);

    await waitFor(() => expect(location()).toBe('/my'));
    expect((await searchBox()).value).toBe('NVDA');
  });

  test('주소로 바로 연결 화면에 들어와 취소하면 내 종목으로 바뀐다', async () => {
    const server = createFakeServer();
    myMember(server);
    const { user, location } = openMy('/my?account=connect');

    await user.click(await screen.findByRole('button', { name: '취소' }));

    expect(location()).toBe('/my');
    expect(
      await screen.findByRole('heading', { name: '내 종목' }),
    ).toBeTruthy();
  });

  test('연결에 실패하면 연결 화면에 머물고, 다시 시도해 성공하면 돌아온다', async () => {
    const server = createFakeServer();
    myMember(server);
    server.on('POST', '/api/v1/portfolio/connections', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    const { user, location } = openMy('/my?account=connect');

    await screen.findByRole('list', { name: '가상 계좌 목록' });
    await user.click(
      screen.getByRole('button', { name: '선택한 가상 계좌 연결하기' }),
    );
    expect((await screen.findByRole('alert')).textContent).toContain(
      '계좌를 연결하지 못했어요',
    );
    expect(location()).toBe('/my?account=connect');

    myMember(server);
    await user.click(screen.getByRole('button', { name: '다시 연결하기' }));

    await waitFor(() => expect(location()).toBe('/my'));
  });

  test('[연결 끊기]는 확인 창을 열 뿐이고, [닫기]를 고르면 요청하지 않는다', async () => {
    const server = createFakeServer();
    myMember(server, { connected: true });
    const { user } = openMy();

    const section = await holdingsSection();
    await user.click(
      await within(section).findByRole('button', { name: '연결 끊기' }),
    );

    const dialog = screen.getByRole('dialog', {
      name: '가상 계좌 연결을 끊을까요?',
    });
    expect(server.calls('DELETE', DELETE_CONNECTION)).toHaveLength(0);

    await user.click(within(dialog).getByRole('button', { name: '닫기' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(server.calls('DELETE', DELETE_CONNECTION)).toHaveLength(0);
    expect(within(section).getByText('삼성전자')).toBeTruthy();
  });

  test('확인 창에서 끊으면 보유 표시만 해제하고 관심 종목은 그대로 둔다', async () => {
    const server = createFakeServer();
    myMember(server, { connected: true, watchlistIds: ['cmp-nvidia'] });
    const { user } = openMy();

    const section = await holdingsSection();
    await user.click(
      await within(section).findByRole('button', { name: '연결 끊기' }),
    );
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', {
        name: '연결 끊기',
      }),
    );

    expect(await within(section).findByText('연결 안 됨')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(within(section).queryByText('삼성전자')).toBeNull();
    expect(server.calls('DELETE', DELETE_CONNECTION)[0].params.id).toBe(
      'conn-1',
    );
    const watchlist = screen.getByRole('list', { name: '관심 종목 목록' });
    expect(await within(watchlist).findByText('NVIDIA')).toBeTruthy();
  });

  test('끊기에 실패하면 창에 안내하고 연결·보유 목록을 유지하며, 다시 누르면 다시 시도한다', async () => {
    const server = createFakeServer();
    myMember(server, { connected: true });
    server.on('DELETE', DELETE_CONNECTION, () =>
      apiError(500, 'INTERNAL_ERROR'),
    );
    const { user } = openMy();

    const section = await holdingsSection();
    await user.click(
      await within(section).findByRole('button', { name: '연결 끊기' }),
    );
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: '연결 끊기' }));

    expect((await within(dialog).findByRole('alert')).textContent).toContain(
      '연결을 끊지 못했어요',
    );
    expect(within(section).getByText('삼성전자')).toBeTruthy();
    expect(within(section).queryByText('연결 안 됨')).toBeNull();

    myMember(server, { connected: true });
    await user.click(within(dialog).getByRole('button', { name: '연결 끊기' }));

    expect(await within(section).findByText('연결 안 됨')).toBeTruthy();
    expect(server.calls('DELETE', DELETE_CONNECTION)).toHaveLength(2);
  });

  test('보유 종목을 불러오지 못하면 그 영역만 안내하고 다시 시도한다', async () => {
    const server = createFakeServer();
    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    server.on('GET', '/api/v1/portfolio', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    const { user } = openMy();

    const section = await holdingsSection();
    expect((await within(section).findByRole('alert')).textContent).toContain(
      '보유 종목을 불러오지 못했어요',
    );
    expect(await screen.findByText('NVIDIA')).toBeTruthy();

    myMember(server, { connected: true, watchlistIds: ['cmp-nvidia'] });
    await user.click(
      within(section).getByRole('button', { name: '다시 시도' }),
    );

    expect(await within(section).findByText('삼성전자')).toBeTruthy();
  });

  test('연결 요청은 실패했지만 이미 연결된 것으로 확인되면, 돌아온 내 종목에 보유 종목을 보여 준다', async () => {
    const server = createFakeServer();
    const state = myMember(server);
    // 다른 탭에서 먼저 연결했거나 응답만 유실된 경우
    server.on('POST', '/api/v1/portfolio/connections', () => {
      state.connected = true;
      return apiError(409, 'REVISION_CONFLICT');
    });
    const { user, location } = openMy();

    await user.click(
      await screen.findByRole('button', { name: '가상 계좌 연결하기' }),
    );
    await screen.findByRole('list', { name: '가상 계좌 목록' });
    await user.click(
      screen.getByRole('button', { name: '선택한 가상 계좌 연결하기' }),
    );
    await user.click(
      await screen.findByRole('button', { name: '내 종목으로 돌아가기' }),
    );

    await waitFor(() => expect(location()).toBe('/my'));
    const section = await holdingsSection();
    expect(await within(section).findByText('삼성전자')).toBeTruthy();
    expect(within(section).queryByText('연결 안 됨')).toBeNull();
  });

  test('다른 곳에서 이미 끊겼으면 끊기 실패 뒤 창을 닫고 연결 안 됨을 보여 준다', async () => {
    const server = createFakeServer();
    const state = myMember(server, { connected: true });
    server.on('DELETE', DELETE_CONNECTION, () => {
      state.connected = false;
      return apiError(404, 'RESOURCE_NOT_FOUND');
    });
    const { user } = openMy();

    const section = await holdingsSection();
    await user.click(
      await within(section).findByRole('button', { name: '연결 끊기' }),
    );
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: '연결 끊기' }));

    expect(await within(section).findByText('연결 안 됨')).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(server.calls('DELETE', DELETE_CONNECTION)).toHaveLength(1);
  });
});
