import { beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { ComponentType } from 'react';
import OnboardingLayout from '@/components/onboarding/OnboardingLayout';
import InvestmentStatusPage from '@/pages/onboarding/investment/InvestmentStatusPage';
import VirtualAccountPage from '@/pages/onboarding/account/VirtualAccountPage';
import WatchlistSetupPage from '@/pages/onboarding/watchlist/WatchlistSetupPage';
import { createMockGraph } from '@/mocks/graph/response';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import type { GraphRequest, GraphResponse } from '@/types/map/graph';
import { createFakeServer, json } from '../support/fakeServer';
import {
  connectedPortfolioBody,
  connectionBody,
  disconnectedPortfolioBody,
  mockPortfoliosBody,
} from '../support/fixtures';

vi.mock('@/components/graph/GraphCanvas', () => ({
  default: ({ data }: { data: GraphResponse }) => (
    <output data-testid="initial-graph">
      {data.metadata.mode}:
      {data.nodes
        .filter(
          (node) => node.kind === 'company' && (node.holding || node.watch),
        )
        .map(
          (node) =>
            `${node.id}[${node.holding ? 'H' : ''}${node.watch ? 'W' : ''}]`,
        )
        .join(',')}
    </output>
  ),
}));

let MapPage: ComponentType;
beforeAll(async () => {
  vi.stubEnv('VITE_GRAPH_DATA_SOURCE', 'api');
  MapPage = (await import('@/pages/map/MapPage')).default;
});

const samsung = {
  id: 'KRX:005930',
  name: '삼성전자',
  ticker: '005930',
  aliases: [],
  sector: 'IT',
  brandColor: null,
  logoUrl: null,
  issueCount: 27,
};
const nvidia = {
  companyId: 'NASDAQ:NVDA',
  name: 'NVIDIA',
  ticker: 'NVDA',
};

function Location() {
  const location = useLocation();
  return <output data-testid="map-location">{location.search}</output>;
}

beforeEach(() => {
  sessionStorage.clear();
  useOnboardingStore.getState().reset();
  useOnboardingStore.getState().setInvestmentStatus('not-investing');
  useAuthStore.setState({
    status: 'ready',
    session: {
      authenticated: true,
      kind: 'member',
      user: {
        id: 'graph-onboarding',
        email: 'graph@zoop.test',
        displayName: '테스트 회원',
      },
      setup: { completed: false, tutorialCompleted: true },
      csrfToken: 'csrf-test',
      expiresAt: null,
    },
    member: {
      id: 'graph-onboarding',
      email: 'graph@zoop.test',
      displayName: '테스트 회원',
    },
    onboardingCompleted: false,
  });
});

it.each([
  { holdings: false, watch: false, mode: 'all', flags: '' },
  { holdings: true, watch: false, mode: 'personal', flags: 'NASDAQ:NVDA[H]' },
  { holdings: false, watch: true, mode: 'personal', flags: 'KRX:005930[W]' },
  {
    holdings: true,
    watch: true,
    mode: 'personal',
    flags: 'NASDAQ:NVDA[H],KRX:005930[W]',
  },
] as const)(
  'FS014/#45 · D-WAT-01 → D-GRP-01/01b: holdings=$holdings watch=$watch',
  async ({ holdings, watch, mode, flags }) => {
    const server = createFakeServer();
    let watchlistIds: string[] = [];
    server.on('GET', '/api/v1/me/settings', () =>
      json({
        mode: null,
        watchlistIds,
        completed: false,
        tutorialCompleted: true,
        investor: false,
        version: 1,
      }),
    );
    server.on('GET', '/api/v1/portfolio', () =>
      json({
        connected: holdings,
        connection: null,
        holdings: holdings ? [nvidia] : [],
        mockAsOf: null,
        valuation: null,
      }),
    );
    server.on('GET', '/api/v1/companies', (request) =>
      json({
        items: request.query.get('q') ? [samsung] : [],
        nextCursor: null,
      }),
    );
    server.on('PUT', '/api/v1/me/settings', (request) => {
      watchlistIds = (request.body as { watchlistIds: string[] }).watchlistIds;
      return json({ ...(request.body as object), tutorialCompleted: true });
    });
    server.on('GET', '/api/v1/graph', (request) => {
      const graphRequest: GraphRequest = {
        mode: request.query.get('mode') === 'personal' ? 'personal' : 'all',
        personalFilter: 'all',
      };
      return json(
        createMockGraph(graphRequest, 'success', {
          holdings: holdings ? [nvidia.companyId] : [],
          watchlist: watchlistIds,
        }),
      );
    });
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/onboarding/watchlist']}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingLayout />}>
            <Route path="watchlist" element={<WatchlistSetupPage />} />
          </Route>
          <Route
            path="/"
            element={
              <>
                <Location />
                <MapPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: '고르지 않고 지도 보기' })
          .hasAttribute('disabled'),
      ).toBe(false),
    );
    if (watch) {
      await user.type(
        screen.getByLabelText('기업명이나 종목 코드'),
        '삼성{Enter}',
      );
      await user.click(
        await screen.findByRole('button', { name: '삼성전자 추가' }),
      );
    }
    await user.click(
      screen.getByRole('button', {
        name: watch ? '1개 종목으로 시작하기' : '고르지 않고 지도 보기',
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('map-location').textContent).toContain(
        `mode=${mode}`,
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId('initial-graph').textContent).toBe(
        `${mode}:${flags}`,
      ),
    );
    expect(server.calls('GET', '/api/v1/graph').at(-1)?.query.get('mode')).toBe(
      mode,
    );
    expect(server.calls('PUT', '/api/v1/me/settings')[0]?.body).toMatchObject({
      watchlistIds: watch ? [samsung.id] : [],
      completed: true,
    });
  },
);

it('FS014/#45 · D-ONB-01 → D-ONB-02 → D-WAT-01 → D-GRP-01b keeps the connected holdings', async () => {
  const server = createFakeServer();
  let investor: boolean | null = null;
  let version = 1;
  let connected = false;
  server.on('GET', '/api/v1/me/settings', () =>
    json({
      mode: null,
      watchlistIds: [],
      completed: false,
      tutorialCompleted: true,
      investor,
      version,
    }),
  );
  server.on('PUT', '/api/v1/me/settings', (request) => {
    const body = request.body as {
      investor?: boolean;
      version: number;
      completed?: boolean;
    };
    expect(body.version).toBe(version);
    if (body.investor !== undefined) investor = body.investor;
    version += 1;
    return json({
      ...body,
      mode: body.completed ? 'assets' : null,
      investor,
      version,
      completed: Boolean(body.completed),
      watchlistIds: [],
      tutorialCompleted: true,
    });
  });
  server.on('GET', '/api/v1/portfolio/mock-portfolios', () =>
    json(mockPortfoliosBody()),
  );
  server.on('GET', '/api/v1/portfolio', () =>
    json(connected ? connectedPortfolioBody() : disconnectedPortfolioBody()),
  );
  server.on('POST', '/api/v1/portfolio/connections', (request) => {
    connected = true;
    return json(
      connectionBody(
        (request.body as { mockPortfolioId: string }).mockPortfolioId,
      ),
      201,
    );
  });
  server.on('GET', '/api/v1/graph', (request) =>
    json(
      createMockGraph(
        {
          mode: request.query.get('mode') === 'personal' ? 'personal' : 'all',
          personalFilter: 'all',
        },
        'success',
        {
          holdings: connected ? ['KRX:005930'] : [],
          watchlist: [],
        },
      ),
    ),
  );
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/onboarding']}>
      <Routes>
        <Route path="/onboarding" element={<OnboardingLayout />}>
          <Route index element={<InvestmentStatusPage />} />
          <Route path="account" element={<VirtualAccountPage />} />
          <Route path="watchlist" element={<WatchlistSetupPage />} />
        </Route>
        <Route
          path="/"
          element={
            <>
              <Location />
              <MapPage />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
  await user.click(
    await screen.findByRole('button', { name: /지금 주식에 투자하고 있어요/ }),
  );
  await screen.findByRole('list', { name: '가상 계좌 목록' });
  await user.click(
    screen.getByRole('button', { name: '선택한 가상 계좌 연결하기' }),
  );
  await screen.findByRole('heading', { name: '가상 계좌를 연결했어요' });
  await user.click(screen.getByRole('button', { name: '관심 종목 고르기' }));
  await waitFor(() =>
    expect(
      screen
        .getByRole('button', { name: '고르지 않고 지도 보기' })
        .hasAttribute('disabled'),
    ).toBe(false),
  );
  await user.click(
    screen.getByRole('button', { name: '고르지 않고 지도 보기' }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('initial-graph').textContent).toBe(
      'personal:KRX:005930[H]',
    ),
  );
  expect(server.calls('POST', '/api/v1/portfolio/connections')).toHaveLength(1);
  expect(server.calls('PUT', '/api/v1/me/settings')).toHaveLength(2);
});
