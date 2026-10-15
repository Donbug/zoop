import { screen, waitFor, within } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import MyStocksPage from '@/pages/my/MyStocksPage';
import { settingsBody } from '../support/fixtures';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';
import { myMember } from '../support/myMember';
import { renderRoutes } from '../support/renderRoutes';

const WATCH = '/api/v1/me/watchlist/:id';
const EMPTY_TEXT =
  '아직 관심 종목이 없어요. 아래에서 기업을 검색해 추가하면 내 종목 지도에 함께 보여요.';
const MARKET_INFO = '보유·관심이 모두 없으면 지도는 시장 전체로 열려요.';
const SAVE_FAILED =
  '관심 종목을 저장하지 못했어요. 목록을 이전 상태로 되돌렸어요.';

function openMy() {
  return renderRoutes([{ path: '/my', element: <MyStocksPage /> }], '/my');
}

const watchSection = () => screen.findByRole('region', { name: '관심 종목' });

const watchNames = () => {
  const list = screen.queryByRole('list', { name: '관심 종목 목록' });
  return list
    ? within(list)
        .getAllByRole('button', { name: /관심 종목에서 빼기$/ })
        .map((button) => button.getAttribute('aria-label'))
    : [];
};

async function searchFor(user: UserEvent, term: string) {
  const box = within(
    await screen.findByRole('search', { name: '관심 종목 추가' }),
  ).getByRole('searchbox');
  await user.clear(box);
  await user.type(box, `${term}{Enter}`);
}

const results = (term: string) =>
  screen.findByRole('list', { name: `‘${term}’ 검색 결과` });

describe('D-MY-01 / 01b 내 종목: 관심 종목', () => {
  test('미연결·관심 0개면 빈 안내와 함께 지도가 시장 전체로 열린다고 알린다', async () => {
    const server = createFakeServer();
    myMember(server);
    openMy();

    const section = await watchSection();
    expect(await within(section).findByText(EMPTY_TEXT)).toBeTruthy();
    expect(await within(section).findByText(MARKET_INFO)).toBeTruthy();
    expect(within(section).getByText('0개')).toBeTruthy();
  });

  test('연결됨·관심 0개면 빈 안내는 있지만 지도 안내는 없다', async () => {
    const server = createFakeServer();
    myMember(server, { connected: true });
    openMy();

    const section = await watchSection();
    expect(await within(section).findByText(EMPTY_TEXT)).toBeTruthy();
    await screen.findByRole('list', { name: '보유 종목 목록' });
    expect(within(section).queryByText(MARKET_INFO)).toBeNull();
  });

  test('미연결·관심 있음이면 계좌 안내와 관심 목록(종목 코드·승인된 사건 수)을 함께 보여 준다', async () => {
    const server = createFakeServer();
    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    openMy();

    expect(await screen.findByText('연결 안 됨')).toBeTruthy();
    const list = await screen.findByRole('list', { name: '관심 종목 목록' });
    expect(
      await within(list).findByText('NVDA · 승인된 사건 46건'),
    ).toBeTruthy();
    expect(
      within(list)
        .getByRole('link', { name: 'NVIDIA, 지도에서 보기' })
        .getAttribute('href'),
    ).toBe('/?mode=personal&select=node:cmp-nvidia');
    expect(screen.queryByText(MARKET_INFO)).toBeNull();
  });

  test("가상 계좌에도 있는 종목은 관심 행과 검색 결과 행에 '보유' 배지를 붙인다", async () => {
    const server = createFakeServer();
    myMember(server, { connected: true, watchlistIds: ['cmp-samsung'] });
    const { user } = openMy();

    const list = await screen.findByRole('list', { name: '관심 종목 목록' });
    expect(await within(list).findByText('보유')).toBeTruthy();

    await searchFor(user, '삼성');
    const found = await results('삼성');
    const samsungRow = within(found).getByText('삼성전자').closest('li');
    const sdiRow = within(found).getByText('삼성SDI').closest('li');
    expect(within(samsungRow as HTMLElement).getByText('보유')).toBeTruthy();
    expect(within(sdiRow as HTMLElement).queryByText('보유')).toBeNull();
  });

  test('검색 결과에서 추가하면 저장 버튼 없이 바로 저장하고, 응답 전에도 목록에 보인다', async () => {
    const server = createFakeServer();
    const state = myMember(server);
    const response = deferred<Response>();
    server.on('PUT', WATCH, () => response.promise);
    const { user } = openMy();

    await searchFor(user, '삼성');
    await user.click(
      within(await results('삼성')).getByRole('button', {
        name: '삼성전자 관심 추가',
      }),
    );

    expect(watchNames()).toEqual(['삼성전자 관심 종목에서 빼기']);
    expect((await watchSection()).textContent).toContain('1개 · 저장 중');
    // 저장 중에는 다른 변경을 막는다.
    expect(
      within(await results('삼성'))
        .getByRole('button', { name: '삼성SDI 관심 추가' })
        .hasAttribute('disabled'),
    ).toBe(true);
    expect(
      screen
        .getByRole('button', { name: '삼성전자 관심 종목에서 빼기' })
        .hasAttribute('disabled'),
    ).toBe(true);

    const put = server.calls('PUT', WATCH)[0];
    expect(put.params.id).toBe('cmp-samsung');
    expect(put.body).toEqual({ watched: true });

    state.settings = { ...state.settings, watchlistIds: ['cmp-samsung'] };
    response.resolve(json(settingsBody(state.settings)));

    await waitFor(() =>
      expect(
        screen.getByRole('region', { name: '관심 종목' }).textContent,
      ).not.toContain('저장 중'),
    );
    expect(watchNames()).toEqual(['삼성전자 관심 종목에서 빼기']);
    expect(server.calls('GET', '/api/v1/companies/:id')).toHaveLength(0);
  });

  test('빼기 저장에 실패하면 목록을 되돌리고 하단 알림의 [다시 시도]로 같은 변경을 다시 보낸다', async () => {
    const server = createFakeServer();
    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    server.on('PUT', WATCH, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = openMy();

    await searchFor(user, 'NVDA');
    await results('NVDA');
    await user.click(
      await screen.findByRole('button', { name: 'NVIDIA 관심 종목에서 빼기' }),
    );

    expect((await screen.findByRole('alert')).textContent).toContain(
      SAVE_FAILED,
    );
    expect(watchNames()).toEqual(['NVIDIA 관심 종목에서 빼기']);
    // 검색어와 결과는 그대로다.
    expect(screen.getByRole('list', { name: '‘NVDA’ 검색 결과' })).toBeTruthy();

    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    await user.click(screen.getByRole('button', { name: '다시 시도' }));

    await waitFor(() => expect(watchNames()).toEqual([]));
    expect(screen.queryByText(SAVE_FAILED)).toBeNull();
    const puts = server.calls('PUT', WATCH);
    expect(puts).toHaveLength(2);
    expect(puts.map((put) => [put.params.id, put.body])).toEqual([
      ['cmp-nvidia', { watched: false }],
      ['cmp-nvidia', { watched: false }],
    ]);
    expect(await screen.findByText(EMPTY_TEXT)).toBeTruthy();
  });

  test('추가 저장에 실패해도 추가 전 목록으로 되돌린다', async () => {
    const server = createFakeServer();
    myMember(server);
    server.on('PUT', WATCH, () => apiError(500, 'INTERNAL_ERROR'));
    const { user } = openMy();

    await searchFor(user, '삼성');
    await user.click(
      within(await results('삼성')).getByRole('button', {
        name: '삼성SDI 관심 추가',
      }),
    );

    expect((await screen.findByRole('alert')).textContent).toContain(
      SAVE_FAILED,
    );
    expect(watchNames()).toEqual([]);
    expect(screen.getByText(EMPTY_TEXT)).toBeTruthy();
  });

  test('관심 종목을 불러오지 못하면 그 영역만 안내하고, 다시 시도해 성공하면 보여 준다', async () => {
    const server = createFakeServer();
    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    server.on('GET', '/api/v1/me/settings', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    const { user } = openMy();

    const section = await watchSection();
    expect((await within(section).findByRole('alert')).textContent).toContain(
      '관심 종목을 불러오지 못했어요',
    );
    // 조회 실패를 0개로 보지 않는다.
    expect(within(section).queryByText(EMPTY_TEXT)).toBeNull();
    expect(screen.queryByRole('search', { name: '관심 종목 추가' })).toBeNull();

    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    await user.click(
      within(section).getByRole('button', { name: '다시 시도' }),
    );

    expect(await within(section).findByText('NVIDIA')).toBeTruthy();
  });

  test('관심 행의 기업 정보를 불러오지 못하면 그 행에서 다시 시도한다', async () => {
    const server = createFakeServer();
    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    server.on('GET', '/api/v1/companies/:id', () =>
      apiError(503, 'SOURCE_UNAVAILABLE'),
    );
    const { user } = openMy();

    expect(
      await screen.findByText('종목 정보를 불러오지 못했어요.'),
    ).toBeTruthy();

    myMember(server, { watchlistIds: ['cmp-nvidia'] });
    await user.click(
      screen.getByRole('button', { name: '종목 정보 다시 불러오기' }),
    );

    expect(await screen.findByText('NVIDIA')).toBeTruthy();
    expect(screen.queryByText('종목 정보를 불러오지 못했어요.')).toBeNull();
  });
});
