import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import VirtualAccountPage from '@/pages/onboarding/account/VirtualAccountPage';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import {
  connectedPortfolioBody,
  connectionBody,
  disconnectedPortfolioBody,
  mockPortfoliosBody,
  SAMSUNG_HOLDING,
} from '../support/fixtures';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const OPTIONS = '/api/v1/portfolio/mock-portfolios';
const PORTFOLIO = '/api/v1/portfolio';
const CONNECTIONS = '/api/v1/portfolio/connections';
const PROFILE_PREVIEW = `${OPTIONS}/mock-1`;

function profilePreviewBody(id = 'mock-1') {
  const selected = id === 'mock-2';
  return {
    id,
    label: selected ? '배당주 계좌' : '성장주 계좌',
    accountId: selected ? 'MOCK-0002' : 'MOCK-0001',
    cash: { amount: 500000, currency: 'KRW' },
    asOf: '2026-10-06T03:41:00Z',
    holdings: [{ ...SAMSUNG_HOLDING, weight: 0.6 }],
    valuation: {
      calculatedAt: '2026-10-06T03:41:00Z',
      currency: 'KRW',
      totalMarketValue: 9050000,
      weightStatus: 'available',
      weightUnavailableCode: null,
      weightUnavailableReason: null,
    },
    metadata: { source: 'test' },
  };
}

/** 미연결 회원. 연결하면 이후 GET /portfolio가 연결된 상태를 돌려준다. */
function notConnectedMember(server: FakeServer) {
  let connected = false;
  server.on('GET', OPTIONS, () => json(mockPortfoliosBody()));
  server.on('GET', `${OPTIONS}/:id`, ({ params }) =>
    json(profilePreviewBody(params.id)),
  );
  server.on('GET', PORTFOLIO, () =>
    json(connected ? connectedPortfolioBody() : disconnectedPortfolioBody()),
  );
  server.on('POST', CONNECTIONS, ({ body }) => {
    connected = true;
    return json(
      connectionBody((body as { mockPortfolioId: string }).mockPortfolioId),
      201,
    );
  });
}

function openAccountStep() {
  return renderRoutes(
    [{ path: '/onboarding/account', element: <VirtualAccountPage /> }],
    '/onboarding/account',
  );
}

const accountButton = (name: RegExp) =>
  within(screen.getByRole('list', { name: '가상 계좌 목록' })).getByRole(
    'button',
    { name },
  );
/** 지금까지 보낸 연결 요청의 Idempotency-Key */
const connectKeys = () =>
  vi
    .mocked(fetch)
    .mock.calls.filter(
      ([url, init]) =>
        String(url).endsWith(CONNECTIONS) && init?.method === 'POST',
    )
    .map(([, init]) => new Headers(init?.headers).get('Idempotency-Key'));

const connectButton = () =>
  screen.getByRole('button', {
    name: /선택한 가상 계좌 연결하기|다시 연결하기/,
  });

describe('D-ONB-02 가상 계좌 연결', () => {
  test('계좌를 선택하면 연결 전에 종목과 비중을 조회 전용으로 보여 준다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    openAccountStep();

    const holdings = await screen.findByRole('list', {
      name: '미리보기 보유 종목',
    });
    expect(within(holdings).getByText('삼성전자')).toBeTruthy();
    expect(within(holdings).getByText('비중 60%')).toBeTruthy();
    expect(server.calls('GET', PROFILE_PREVIEW)).toHaveLength(1);
    expect(server.calls('POST', CONNECTIONS)).toHaveLength(0);
  });

  test('고른 계좌를 연결하면 보유 종목을 보여 주고 [관심 종목 고르기]로만 넘어간다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    const { user, location } = openAccountStep();

    expect(
      await screen.findByText(
        '실제 증권 계좌가 아니에요. 준비된 모의 데이터로 만든 가상 계좌예요.',
      ),
    ).toBeTruthy();
    await screen.findByRole('list', { name: '가상 계좌 목록' });
    expect(accountButton(/성장주 계좌/).getAttribute('aria-pressed')).toBe(
      'true',
    );
    await user.click(accountButton(/배당주 계좌/));
    await user.click(connectButton());

    expect(
      await screen.findByRole('heading', { name: '가상 계좌를 연결했어요' }),
    ).toBeTruthy();
    expect(await screen.findByText('삼성전자')).toBeTruthy();
    expect(server.calls('POST', CONNECTIONS)[0].body).toEqual({
      mockPortfolioId: 'mock-2',
    });
    expect(useOnboardingStore.getState().virtualAccountId).toBe('conn-1');
    expect(screen.queryByRole('button', { name: /지도/ })).toBeNull();
    expect(screen.queryByRole('button', { name: '이전 단계' })).toBeNull();

    await user.click(screen.getByRole('button', { name: '관심 종목 고르기' }));
    expect(location()).toBe('/onboarding/watchlist');
  });

  test('건너뛰면 연결하지 않고 관심 종목 선택으로 간다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    const { user, location } = openAccountStep();

    await user.click(
      await screen.findByRole('button', { name: '건너뛰고 관심 종목 고르기' }),
    );

    expect(location()).toBe('/onboarding/watchlist');
    expect(server.calls('POST', CONNECTIONS)).toHaveLength(0);
  });

  test('[이전 단계]는 투자 여부 선택으로 돌아간다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    const { user, location } = openAccountStep();

    await user.click(await screen.findByRole('button', { name: /이전 단계/ }));

    expect(location()).toBe('/onboarding');
  });

  test('연결 중에는 다른 계좌 선택·건너뛰기·이전 단계를 막는다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    const response = deferred<Response>();
    server.on('POST', CONNECTIONS, () => response.promise);
    const { user } = openAccountStep();

    await screen.findByRole('list', { name: '가상 계좌 목록' });
    await user.click(connectButton());

    expect(
      screen
        .getByRole('button', { name: '연결하고 있어요' })
        .hasAttribute('disabled'),
    ).toBe(true);
    expect(accountButton(/배당주 계좌/).hasAttribute('disabled')).toBe(true);
    expect(
      screen
        .getByRole('button', { name: '건너뛰고 관심 종목 고르기' })
        .hasAttribute('disabled'),
    ).toBe(true);
    expect(
      screen
        .getByRole('button', { name: /이전 단계/ })
        .hasAttribute('disabled'),
    ).toBe(true);

    response.resolve(json(connectionBody('mock-1'), 201));
    expect(
      await screen.findByRole('heading', { name: '가상 계좌를 연결했어요' }),
    ).toBeTruthy();
  });

  test('연결에 실패하면 고른 계좌를 그대로 두고, 다시 시도해 성공하면 보유 종목을 보여 준다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    server.on('POST', CONNECTIONS, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = openAccountStep();

    await screen.findByRole('list', { name: '가상 계좌 목록' });
    await user.click(accountButton(/배당주 계좌/));
    await user.click(connectButton());

    expect((await screen.findByRole('alert')).textContent).toContain(
      '계좌를 연결하지 못했어요',
    );
    expect(accountButton(/배당주 계좌/).getAttribute('aria-pressed')).toBe(
      'true',
    );

    notConnectedMember(server);
    // 실패 뒤 연결 상태를 다시 확인하는 동안에는 연결 버튼이 잠긴다.
    await waitFor(() =>
      expect(connectButton().hasAttribute('disabled')).toBe(false),
    );
    await user.click(screen.getByRole('button', { name: '다시 연결하기' }));

    expect(await screen.findByText('삼성전자')).toBeTruthy();
    const posts = server.calls('POST', CONNECTIONS);
    expect(posts).toHaveLength(2);
    expect(posts[1].body).toEqual({ mockPortfolioId: 'mock-2' });
    // 같은 연결 시도를 다시 보낼 때는 같은 Idempotency-Key를 쓴다.
    const [first, retry] = connectKeys();
    expect(first).toBeTruthy();
    expect(retry).toBe(first);
  });

  test('다른 계좌로 바꿔 연결하면 새 Idempotency-Key를 쓴다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    server.on('POST', CONNECTIONS, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = openAccountStep();

    await screen.findByRole('list', { name: '가상 계좌 목록' });
    await user.click(connectButton());
    await screen.findByRole('alert');
    await waitFor(() =>
      expect(connectButton().hasAttribute('disabled')).toBe(false),
    );
    await user.click(accountButton(/배당주 계좌/));
    await user.click(connectButton());
    await waitFor(() => expect(connectKeys()).toHaveLength(2));

    const [first, second] = connectKeys();
    expect(second).toBeTruthy();
    expect(second).not.toBe(first);
  });

  test('연결 요청이 실패했지만 실제로는 연결됐으면 연결 완료 화면으로 넘어간다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    // 응답은 실패로 왔지만 서버에는 연결이 반영된 경우(다른 탭·응답 유실)
    let connected = false;
    server.on('GET', PORTFOLIO, () =>
      json(connected ? connectedPortfolioBody() : disconnectedPortfolioBody()),
    );
    server.on('POST', CONNECTIONS, () => {
      connected = true;
      return apiError(409, 'REVISION_CONFLICT');
    });
    const { user } = openAccountStep();

    await screen.findByRole('list', { name: '가상 계좌 목록' });
    await user.click(connectButton());

    expect(
      await screen.findByRole('heading', { name: '가상 계좌를 연결했어요' }),
    ).toBeTruthy();
    expect(screen.getByText('삼성전자')).toBeTruthy();
    expect(server.calls('POST', CONNECTIONS)).toHaveLength(1);
  });

  test('연결 상태를 확인하지 못하면 연결을 막고, 다시 시도해 성공하면 연결할 수 있다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    server.on('GET', PORTFOLIO, () => apiError(500, 'INTERNAL_ERROR'));
    const { user } = openAccountStep();

    expect((await screen.findByRole('alert')).textContent).toContain(
      '지금 계좌 연결 상태를 확인하지 못했어요',
    );
    expect(connectButton().hasAttribute('disabled')).toBe(true);

    server.on('GET', PORTFOLIO, () => json(disconnectedPortfolioBody()));
    await user.click(screen.getByRole('button', { name: '다시 시도' }));

    await waitFor(() =>
      expect(connectButton().hasAttribute('disabled')).toBe(false),
    );
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('계좌 목록을 불러오지 못하면 연결을 막고, 다시 시도해 성공하면 목록을 보여 준다', async () => {
    const server = createFakeServer();
    notConnectedMember(server);
    server.on('GET', OPTIONS, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = openAccountStep();

    expect((await screen.findByRole('alert')).textContent).toContain(
      '가상 계좌를 불러오지 못했어요',
    );
    expect(connectButton().hasAttribute('disabled')).toBe(true);

    server.on('GET', OPTIONS, () => json(mockPortfoliosBody()));
    await user.click(screen.getByRole('button', { name: '다시 시도' }));

    expect(
      await screen.findByRole('list', { name: '가상 계좌 목록' }),
    ).toBeTruthy();
    expect(connectButton().hasAttribute('disabled')).toBe(false);
  });

  test('이미 연결돼 있으면 보유 종목과 [관심 종목 고르기]를 보여 준다', async () => {
    const server = createFakeServer();
    server.on('GET', OPTIONS, () => json(mockPortfoliosBody()));
    server.on('GET', PORTFOLIO, () => json(connectedPortfolioBody()));
    openAccountStep();

    expect(
      await screen.findByRole('heading', { name: '배당주 계좌 보유 종목' }),
    ).toBeTruthy();
    expect(screen.getByText('삼성전자')).toBeTruthy();
    expect(
      screen.getByRole('button', { name: '관심 종목 고르기' }),
    ).toBeTruthy();
  });
});
