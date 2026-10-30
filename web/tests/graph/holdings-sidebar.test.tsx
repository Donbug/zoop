import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import HoldingsSidebar from '@/components/graph/HoldingsSidebar';
import { apiError, createFakeServer, json } from '../support/fakeServer';
import { myMember } from '../support/myMember';
import { NVIDIA, SAMSUNG } from '../support/fixtures';
import { createMockGraph } from '@/mocks/graph/response';

// D-GRP-01/01b: the my-stocks sidebar lists the member's holdings and moves the map to one.
const holding = (companyId: string, name: string, quantity: number) => ({
  companyId,
  name,
  ticker: null,
  quantity,
  avgPrice: 1,
  avgPriceCurrency: 'KRW',
  quote: { status: 'unavailable', reason: 'test' },
  marketValue: null,
  weight: null,
});
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  server = createFakeServer();
  myMember(server);
  server.on('GET', '/api/v1/companies/:id/quote', ({ params }) =>
    json({
      status: 'available',
      companyId: params.id,
      quote: { currency: 'KRW', price: 212000, changeRate: -0.0275 },
    }),
  );
});

it('lists watched companies and saves a star only after the API confirms it', async () => {
  const state = myMember(server, {
    connected: true,
    watchlistIds: [NVIDIA.id],
  });
  const onWatchChanged = vi.fn();
  render(
    <MemoryRouter>
      <HoldingsSidebar
        member
        logoOf={() => null}
        onPick={vi.fn()}
        onClose={vi.fn()}
        onWatchChanged={onWatchChanged}
      />
    </MemoryRouter>,
  );
  const watch = await screen.findByRole('region', { name: '관심 종목' });
  const star = await within(watch).findByRole('button', {
    name: 'NVIDIA 관심 종목',
  });
  expect(star.getAttribute('aria-pressed')).toBe('true');
  await userEvent.click(star);
  await waitFor(() =>
    expect(state.settings.watchlistIds).not.toContain(NVIDIA.id),
  );
  expect(onWatchChanged).toHaveBeenCalledOnce();
  expect(
    await within(watch).findByText(/고른 관심 종목이 없어요/),
  ).toBeTruthy();
  expect(onWatchChanged).toHaveBeenCalledWith([]);
});

// #388 리뷰: 기업 상세에서 저장한 관심 목록도 사이드바의 별·목록·빈 안내에 반영한다.
it('applies a watchlist saved elsewhere on the map', async () => {
  myMember(server, { connected: true, watchlistIds: [NVIDIA.id] });
  const sidebar = (watchSync: { ids: string[]; seq: number } | null) => (
    <MemoryRouter>
      <HoldingsSidebar
        member
        logoOf={() => null}
        onPick={vi.fn()}
        onClose={vi.fn()}
        watchSync={watchSync}
      />
    </MemoryRouter>
  );
  const { rerender } = render(sidebar(null));
  const watch = await screen.findByRole('region', { name: '관심 종목' });
  await within(watch).findByRole('button', { name: 'NVIDIA 관심 종목' });

  rerender(sidebar({ ids: [], seq: 1 }));
  expect(
    await within(watch).findByText(/고른 관심 종목이 없어요/),
  ).toBeTruthy();

  rerender(sidebar({ ids: [SAMSUNG.id], seq: 2 }));
  const star = await within(watch).findByRole('button', {
    name: `${SAMSUNG.name} 관심 종목`,
  });
  expect(star.getAttribute('aria-pressed')).toBe('true');
});

it('keeps the saved star and reports a failed write', async () => {
  myMember(server, { connected: true });
  server.on('PUT', '/api/v1/me/watchlist/:id', () =>
    apiError(503, 'SOURCE_UNAVAILABLE'),
  );
  renderSidebar();
  const star = await screen.findByRole('button', {
    name: `${SAMSUNG.name} 관심 종목`,
  });
  await userEvent.click(star);
  expect((await screen.findByRole('alert')).textContent).toContain(
    '저장 결과를 확인하지 못했어요',
  );
  expect(star.getAttribute('aria-pressed')).toBe('false');
});

it('marks only a visible company with no edges in a complete graph', async () => {
  myMember(server, { connected: true });
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      connection: null,
      holdings: [holding('KRX:005930', '삼성전자', 1)],
    }),
  );
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  graph.edges = graph.edges.filter(
    (edge) => edge.source !== 'KRX:005930' && edge.target !== 'KRX:005930',
  );
  render(
    <MemoryRouter>
      <HoldingsSidebar
        member
        graph={graph}
        logoOf={() => null}
        onPick={vi.fn()}
        onClose={vi.fn()}
      />
    </MemoryRouter>,
  );
  const company = await screen.findByRole('button', {
    name: `${SAMSUNG.name}, 지도에서 보기`,
  });
  expect(company.textContent).toContain('연결된 사건 없음');
});

it('does not claim no linked events when the graph is partial', async () => {
  myMember(server, { connected: true });
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      connection: null,
      holdings: [holding('KRX:005930', '삼성전자', 1)],
    }),
  );
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  graph.edges = [];
  graph.metadata.partial = true;
  render(
    <MemoryRouter>
      <HoldingsSidebar
        member
        graph={graph}
        logoOf={() => null}
        onPick={vi.fn()}
        onClose={vi.fn()}
      />
    </MemoryRouter>,
  );
  const company = await screen.findByRole('button', {
    name: '삼성전자, 지도에서 보기',
  });
  expect(company.textContent).not.toContain('연결된 사건 없음');
});

function renderSidebar(member = true) {
  const onPick = vi.fn();
  render(
    <MemoryRouter>
      <HoldingsSidebar
        member={member}
        logoOf={(id) =>
          id === 'KRX:005930' ? '/graph-assets/samsung.svg' : null
        }
        onPick={onPick}
        onClose={() => undefined}
      />
    </MemoryRouter>,
  );
  return onPick;
}

it('lists holdings with their quote and picks one for the map', async () => {
  server.on('GET', '/api/v1/portfolio', () =>
    json({
      connected: true,
      connection: null,
      holdings: [
        holding('KRX:005930', '삼성전자', 12),
        holding('NASDAQ:META', '메타', 3),
      ],
      mockAsOf: null,
    }),
  );
  const onPick = renderSidebar();
  expect(screen.getByRole('heading', { name: '내 종목' })).toBeTruthy();
  const samsung = await screen.findByRole('button', {
    name: '삼성전자, 지도에서 보기',
  });
  expect(samsung.querySelector('img')?.getAttribute('src')).toBe(
    '/graph-assets/samsung.svg',
  );
  expect(samsung.textContent).toContain('12주');
  await userEvent.click(samsung);
  expect(onPick).toHaveBeenCalledWith('KRX:005930');
});

it('hides the holdings section when the portfolio has no positions', async () => {
  server.on('GET', '/api/v1/portfolio', () =>
    json({ connected: false, connection: null, holdings: [], mockAsOf: null }),
  );
  renderSidebar();
  expect(await screen.findByRole('region', { name: '관심 종목' })).toBeTruthy();
  expect(screen.queryByRole('region', { name: '보유 종목' })).toBeNull();
});

it('does not request the portfolio for a guest', () => {
  renderSidebar(false);
  expect(screen.getByText(/로그인하면 가상 계좌의 보유 종목/)).toBeTruthy();
  expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(0);
  expect(server.calls('GET', '/api/v1/me/settings')).toHaveLength(0);
});

it('does not present a partial settings response as an empty watchlist', async () => {
  server.on('GET', '/api/v1/me/settings', () =>
    json({ watchlistIds: [], metadata: { partial: true } }),
  );
  renderSidebar();
  expect((await screen.findByRole('alert')).textContent).toContain(
    '관심 종목을 불러오지 못했어요',
  );
  expect(screen.queryByText(/고른 관심 종목이 없어요/)).toBeNull();
});
