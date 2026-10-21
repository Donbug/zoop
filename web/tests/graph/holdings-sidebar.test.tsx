import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import HoldingsSidebar from '@/components/graph/HoldingsSidebar';
import { createFakeServer, json } from '../support/fakeServer';

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
  server.on('GET', '/api/v1/companies/:id/quote', ({ params }) =>
    json({
      status: 'available',
      companyId: params.id,
      quote: { currency: 'KRW', price: 212000, changeRate: -0.0275 },
    }),
  );
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
  expect(
    screen.getByRole('heading', { name: '내가 보유 중인 종목' }),
  ).toBeTruthy();
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

it('explains an empty portfolio and asks guests to log in', async () => {
  server.on('GET', '/api/v1/portfolio', () =>
    json({ connected: false, connection: null, holdings: [], mockAsOf: null }),
  );
  renderSidebar();
  expect(await screen.findByText(/보유 종목이 없어요/)).toBeTruthy();
});

it('does not request the portfolio for a guest', () => {
  renderSidebar(false);
  expect(screen.getByText(/로그인하면 가상 계좌의 보유 종목/)).toBeTruthy();
  expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(0);
});
