import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import WatchlistSetupPage from '@/pages/onboarding/watchlist/WatchlistSetupPage';
import OnboardingLayout from '@/components/onboarding/OnboardingLayout';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import {
  createFakeServer,
  json,
  apiError,
  deferred,
} from '../support/fakeServer';

const company = {
  id: 'KRX:005930',
  name: '삼성전자',
  ticker: '005930',
  aliases: [],
  sector: 'IT',
  brandColor: null,
  logoUrl: null,
  issueCount: 27,
};
const settings = {
  mode: null,
  watchlistIds: [],
  completed: false,
  tutorialCompleted: false,
  investor: false,
  version: 3,
  metadata: {},
};
const emptyPortfolio = {
  connected: false,
  connection: null,
  holdings: [],
  mockAsOf: null,
  valuation: null,
  metadata: {},
};
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  useOnboardingStore.getState().reset();
  useAuthStore.setState({ member: null, onboardingCompleted: null });
  useAuthStore.getState().setAccessToken('member-test');
  useOnboardingStore.getState().setInvestmentStatus('not-investing');
  server = createFakeServer();
  server.on('GET', '/api/v1/me/settings', () => json(settings));
  server.on('GET', '/api/v1/portfolio', () => json(emptyPortfolio));
  server.on('GET', '/api/v1/companies', () =>
    json({ items: [company], nextCursor: 'ignored', metadata: {} }),
  );
  server.on('PUT', '/api/v1/me/settings', (req) =>
    json({ ...settings, ...(req.body as object) }),
  );
});
function Destination() {
  const location = useLocation();
  return (
    <output data-testid="destination">
      {location.pathname}
      {location.search}
    </output>
  );
}
function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/onboarding/watchlist']}>
      <Routes>
        <Route path="/onboarding" element={<OnboardingLayout />}>
          <Route path="watchlist" element={<WatchlistSetupPage />} />
          <Route index element={<Destination />} />
          <Route path="account" element={<Destination />} />
        </Route>
        <Route path="/" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
}
async function loaded() {
  await waitFor(() =>
    expect(
      screen
        .getByRole('button', { name: '고르지 않고 지도 보기' })
        .hasAttribute('disabled'),
    ).toBe(false),
  );
}
async function choose() {
  const user = userEvent.setup();
  await loaded();
  await user.type(screen.getByLabelText('기업명이나 종목 코드'), '삼성{Enter}');
  await user.click(
    await screen.findByRole('button', { name: '삼성전자 추가' }),
  );
  return user;
}
describe('Issue #11 · WBS 6.4.5 · D-WAT-01/01b', () => {
  it('allows zero stocks, completes setup, and opens market all', async () => {
    renderPage();
    await loaded();
    expect(
      screen.getByText('관심 종목 없이 시작하면 시장 전체 지도가 열려요.'),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole('button', { name: '고르지 않고 지도 보기' }),
    );
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=all',
    );
    expect(server.requests.find((r) => r.method === 'PUT')?.body).toMatchObject(
      {
        watchlistIds: [],
        version: 3,
        completed: true,
        mode: 'watchlist',
        investor: false,
      },
    );
    expect(useAuthStore.getState().onboardingCompleted).toBe(true);
  });
  it('zero interest with holdings opens personal and uses assets settings mode', async () => {
    server.on('GET', '/api/v1/portfolio', () =>
      json({
        ...emptyPortfolio,
        connected: true,
        holdings: [
          { companyId: company.id, name: company.name, ticker: company.ticker },
        ],
      }),
    );
    renderPage();
    await loaded();
    expect(
      screen.getByText(
        '관심 종목을 추가하지 않아도 보유 종목으로 내 종목 지도를 시작할 수 있어요.',
      ),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole('button', { name: '고르지 않고 지도 보기' }),
    );
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=personal',
    );
    expect(server.requests.find((r) => r.method === 'PUT')?.body).toMatchObject(
      { mode: 'assets' },
    );
  });
  it('search is explicit, prevents duplicates and saves interest to personal', async () => {
    renderPage();
    await loaded();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('기업명이나 종목 코드'), '삼성');
    expect(server.requests.some((r) => r.path === '/api/v1/companies')).toBe(
      false,
    );
    await user.click(screen.getByRole('button', { name: '검색' }));
    await user.click(
      await screen.findByRole('button', { name: '삼성전자 추가' }),
    );
    expect(
      screen
        .getByRole('button', { name: '삼성전자 선택됨' })
        .hasAttribute('disabled'),
    ).toBe(true);
    await user.click(
      screen.getByRole('button', { name: '1개 종목으로 시작하기' }),
    );
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=personal',
    );
    expect(server.requests.find((r) => r.method === 'PUT')?.body).toMatchObject(
      { watchlistIds: [company.id] },
    );
  });
  it('loads existing interest and preserves other settings on save', async () => {
    server.on('GET', '/api/v1/me/settings', () =>
      json({
        ...settings,
        watchlistIds: [company.id],
        tutorialCompleted: true,
        investor: true,
      }),
    );
    useOnboardingStore.getState().setInvestmentStatus(null);
    renderPage();
    await screen.findByRole('button', { name: '1개 종목으로 시작하기' });
    await userEvent.click(
      screen.getByRole('button', { name: '1개 종목으로 시작하기' }),
    );
    await screen.findByTestId('destination');
    const body = server.requests.find((r) => r.method === 'PUT')
      ?.body as Record<string, unknown>;
    expect(body).not.toHaveProperty('tutorialCompleted');
    expect(body).not.toHaveProperty('investor');
  });
  it('last chip removal returns to 0 without clearing the query', async () => {
    renderPage();
    const user = await choose();
    await user.click(screen.getByRole('button', { name: '삼성전자 해제' }));
    expect(
      screen.getByRole('button', { name: '고르지 않고 지도 보기' }),
    ).toBeTruthy();
    expect(
      (screen.getByLabelText('기업명이나 종목 코드') as HTMLInputElement).value,
    ).toBe('삼성');
    expect(
      document
        .querySelector('[data-screen-id]')
        ?.getAttribute('data-screen-id'),
    ).toBe('D-WAT-01');
  });
  it.each(['not-investing', 'investing'] as const)(
    'preserves chips/query across previous step %s',
    async (status) => {
      useOnboardingStore.getState().setInvestmentStatus(status);
      const view = renderPage();
      const user = await choose();
      await user.click(screen.getByRole('button', { name: /이전 단계/ }));
      expect((await screen.findByTestId('destination')).textContent).toBe(
        status === 'not-investing' ? '/onboarding' : '/onboarding/account',
      );
      view.unmount();
      renderPage();
      await screen.findByRole('button', { name: '삼성전자 해제' });
      expect(
        (screen.getByLabelText('기업명이나 종목 코드') as HTMLInputElement)
          .value,
      ).toBe('삼성');
      expect(useOnboardingStore.getState().watchlistIds).toEqual([company.id]);
    },
  );
  it.each(['/api/v1/portfolio', '/api/v1/me/settings'])(
    'blocks completion when %s fails and recovers',
    async (path) => {
      server.on('GET', path, () => apiError(503, 'unavailable'));
      renderPage();
      await screen.findByRole('button', { name: '조회 다시 시도' });
      expect(
        screen
          .getByRole('button', { name: '고르지 않고 지도 보기' })
          .hasAttribute('disabled'),
      ).toBe(true);
      expect(server.requests.some((r) => r.method === 'PUT')).toBe(false);
      server.on('GET', path, () =>
        json(path.includes('portfolio') ? emptyPortfolio : settings),
      );
      await userEvent.click(
        screen.getByRole('button', { name: '조회 다시 시도' }),
      );
      await loaded();
    },
  );
  it('blocks completion until the holdings response arrives', async () => {
    const response = deferred<Response>();
    server.on('GET', '/api/v1/portfolio', () => response.promise);
    renderPage();
    await screen.findByText(/확인하고 있어요/);
    expect(
      screen
        .getByRole('button', { name: '고르지 않고 지도 보기' })
        .hasAttribute('disabled'),
    ).toBe(true);
    await act(async () => response.resolve(json(emptyPortfolio)));
    await loaded();
  });
  it('blocks save/previous/selection and shared navigation while saving; failure retains draft', async () => {
    renderPage();
    const user = await choose();
    const response = deferred<Response>();
    server.on('PUT', '/api/v1/me/settings', () => response.promise);
    await user.click(
      screen.getByRole('button', { name: '1개 종목으로 시작하기' }),
    );
    for (const name of ['삼성전자 해제', '← 이전 단계', '검색']) {
      expect(
        screen.getByRole('button', { name }).hasAttribute('disabled'),
      ).toBe(true);
    }
    expect(screen.queryByRole('link', { name: '투자 여부' })).toBeNull();
    await user.click(screen.getByRole('button', { name: '저장 중…' }));
    expect(server.requests.filter((r) => r.method === 'PUT')).toHaveLength(1);
    await act(async () => response.resolve(apiError(503, 'save_failed')));
    await screen.findByRole('button', { name: '저장 다시 시도' });
    expect(useOnboardingStore.getState().watchlistIds).toEqual([company.id]);
    expect(
      (screen.getByLabelText('기업명이나 종목 코드') as HTMLInputElement).value,
    ).toBe('삼성');
    server.on('PUT', '/api/v1/me/settings', (req) =>
      json({ ...settings, ...(req.body as object) }),
    );
    await user.click(screen.getByRole('button', { name: '저장 다시 시도' }));
    expect((await screen.findByTestId('destination')).textContent).toBe(
      '/?mode=personal',
    );
  });
  it('shows empty/search failure and allows retry', async () => {
    server.on('GET', '/api/v1/companies', () => apiError(503, 'search_failed'));
    renderPage();
    await loaded();
    await userEvent.type(
      screen.getByLabelText('기업명이나 종목 코드'),
      '없음{Enter}',
    );
    await screen.findByRole('button', { name: '검색 다시 시도' });
    server.on('GET', '/api/v1/companies', () =>
      json({ items: [], nextCursor: null }),
    );
    await userEvent.click(
      screen.getByRole('button', { name: '검색 다시 시도' }),
    );
    expect(await screen.findByText('검색 결과가 없어요.')).toBeTruthy();
  });
  it('does not apply an earlier search after the latest result', async () => {
    const old = deferred<Response>();
    server.on('GET', '/api/v1/companies', (req) =>
      req.query.get('q') === '옛검색'
        ? old.promise
        : json({ items: [company] }),
    );
    renderPage();
    await loaded();
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText('기업명이나 종목 코드'),
      '옛검색{Enter}',
    );
    await waitFor(() =>
      expect(server.requests.some((r) => r.query.get('q') === '옛검색')).toBe(
        true,
      ),
    );
    await user.clear(screen.getByLabelText('기업명이나 종목 코드'));
    await user.type(
      screen.getByLabelText('기업명이나 종목 코드'),
      '삼성{Enter}',
    );
    await screen.findByRole('button', { name: '삼성전자 추가' });
    await act(async () => old.resolve(json({ items: [] })));
    expect(screen.getByRole('button', { name: '삼성전자 추가' })).toBeTruthy();
  });
  it('keeps the draft across access-token refresh for the same member', async () => {
    useAuthStore
      .getState()
      .setMember({ id: 'stable-member', displayName: '테스트' }, false);
    renderPage();
    await choose();
    await act(async () =>
      useAuthStore.getState().setAccessToken('refreshed-token'),
    );
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: '1개 종목으로 시작하기' })
          .hasAttribute('disabled'),
      ).toBe(false),
    );
    expect(useOnboardingStore.getState().watchlistIds).toEqual([company.id]);
    expect(
      (screen.getByLabelText('기업명이나 종목 코드') as HTMLInputElement).value,
    ).toBe('삼성');
  });
  it('does not reuse another member draft', async () => {
    const view = renderPage();
    await choose();
    view.unmount();
    useAuthStore.getState().setAccessToken('another-member');
    renderPage();
    await loaded();
    expect(useOnboardingStore.getState().watchlistIds).toEqual([]);
    expect(
      (screen.getByLabelText('기업명이나 종목 코드') as HTMLInputElement).value,
    ).toBe('');
  });
  it('shows the search heading and a held badge for holdings in results', async () => {
    server.on('GET', '/api/v1/portfolio', () =>
      json({
        ...emptyPortfolio,
        connected: true,
        holdings: [
          { companyId: company.id, name: company.name, ticker: company.ticker },
        ],
      }),
    );
    renderPage();
    await choose();
    expect(screen.getByText("'삼성' 검색 결과")).toBeTruthy();
    expect(screen.getByText('1개 종목')).toBeTruthy();
    expect(screen.getByText('보유')).toBeTruthy();
  });
  it('shows names, not ids, for interests saved before entering', async () => {
    server.on('GET', '/api/v1/me/settings', () =>
      json({ ...settings, watchlistIds: [company.id] }),
    );
    server.on('GET', '/api/v1/companies/:id', ({ params }) =>
      json({ id: params.id, name: '삼성전자' }),
    );
    renderPage();
    expect(
      await screen.findByRole('button', { name: '삼성전자 해제' }),
    ).toBeTruthy();
    expect(screen.queryByText(company.id)).toBeNull();
  });
  it('ignores an empty search', async () => {
    renderPage();
    await loaded();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('기업명이나 종목 코드'), '   ');
    await user.click(screen.getByRole('button', { name: '검색' }));
    expect(server.requests.some((r) => r.path === '/api/v1/companies')).toBe(
      false,
    );
  });
});
