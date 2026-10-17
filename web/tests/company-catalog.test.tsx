import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { beforeEach, it, expect } from 'vitest';
import CompanyCatalog from '@/components/company/CompanyCatalog';
import { useAuthStore } from '@/stores/useAuthStore';
import { createFakeServer, json, apiError } from './support/fakeServer';
import { createMockGraph } from '@/mocks/graph/response';
import type { Resource } from '@/hooks/useCompanyResource';
import type { GraphResponse } from '@/types/map/graph';

const company = { id: 'KRX:005930', name: '삼성전자', ticker: '005930' };
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  sessionStorage.clear();
  useAuthStore.getState().clearSession();
  server = createFakeServer();
  server.on('GET', '/api/v1/companies', () =>
    json({ items: [company], nextCursor: null }),
  );
  server.on('GET', '/api/v1/companies/:id/quote', () =>
    json({
      status: 'available',
      companyId: company.id,
      quote: { currency: 'KRW', price: 71900, changeRate: -0.01 },
    }),
  );
});
function open(graph?: Resource<GraphResponse>) {
  return render(
    <MemoryRouter
      initialEntries={['/companies/KRX%3A005930?period=1y&tab=documents']}
    >
      <Routes>
        <Route
          path="/companies/:id"
          element={
            <CompanyCatalog
              graph={graph}
              currentCompany={company}
              portfolio={{
                data: {
                  connected: true,
                  holdings: [{ companyId: company.id }],
                },
                loading: false,
                error: null,
                retry() {},
              }}
            />
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

it('D-COM-01 only loads the next search page on request', async () => {
  server.on('GET', '/api/v1/companies', (request) =>
    json({
      items: [company],
      nextCursor: request.query.get('cursor') ? null : 'second-page',
    }),
  );
  open();
  await userEvent.type(
    screen.getByRole('textbox', { name: '기업명·종목 코드' }),
    '삼성',
  );
  await userEvent.click(screen.getByRole('button', { name: /^검색$/ }));
  const next = await screen.findByRole('button', { name: '다음 검색 결과' });
  expect(
    server
      .calls('GET', '/api/v1/companies')
      .some((request) => request.query.has('cursor')),
  ).toBe(false);
  await userEvent.click(next);
  await screen.findByRole('region', { name: '기업 검색 결과' });
  await within(
    screen.getByRole('region', { name: '기업 검색 결과' }),
  ).findByRole('link', { name: /삼성전자/ });
  expect(
    server
      .calls('GET', '/api/v1/companies')
      .some((request) => request.query.get('cursor') === 'second-page'),
  ).toBe(true);
});
it('D-COM-01 does not present a failed or pending relation lookup as no linked companies', async () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  const { unmount } = open({
    data: null,
    loading: true,
    error: null,
    errorCode: null,
    errorStatus: null,
    retry() {},
  });
  const linked = within(screen.getByRole('region', { name: '연결된 기업' }));
  expect(linked.getByRole('status').textContent).toContain('확인 중');
  expect(linked.queryByText('조회된 연결 기업이 없어요.')).toBeNull();
  unmount();
  open({
    data: graph,
    loading: false,
    error: 'temporary failure',
    errorCode: 'SOURCE_UNAVAILABLE',
    errorStatus: 503,
    retry() {},
  });
  expect(
    within(screen.getByRole('region', { name: '연결된 기업' })).getByRole(
      'alert',
    ).textContent,
  ).toContain('조회 실패');
  expect(screen.queryByText('조회된 연결 기업이 없어요.')).toBeNull();
});
it('D-COM-01 separates personal, recent and linked groups and never reads member settings for guests', async () => {
  open();
  for (const name of ['보유 기업', '관심 기업', '최근 본 기업', '연결된 기업'])
    expect(screen.getByRole('region', { name })).toBeTruthy();
  const recent = within(screen.getByRole('region', { name: '최근 본 기업' }));
  const link = await recent.findByRole('link', { name: /삼성전자/ });
  expect(link.getAttribute('aria-current')).toBe('page');
  expect(link.getAttribute('href')).toContain('period=1y&tab=documents');
  await recent.findByText('▼ -1.00%');
  expect(server.calls('GET', '/api/v1/me/settings')).toHaveLength(0);
  expect(server.calls('GET', '/api/v1/portfolio')).toHaveLength(0);
});
it('D-COM-01 keeps a failed watchlist distinct from an empty one and supports retry', async () => {
  const user = {
    id: 'member',
    email: 'fixture@example.test',
    displayName: '가상 회원',
  };
  useAuthStore.setState({
    status: 'ready',
    member: user,
    session: {
      authenticated: true,
      kind: 'member',
      user,
      setup: { completed: true, tutorialCompleted: true },
      csrfToken: 'fixture',
      expiresAt: null,
    },
  });
  let failed = true;
  server.on('GET', '/api/v1/me/settings', () =>
    failed
      ? apiError(503, 'SOURCE_UNAVAILABLE')
      : json({ watchlistIds: [company.id], completed: true, version: 1 }),
  );
  open();
  const watch = within(screen.getByRole('region', { name: '관심 기업' }));
  await watch.findByRole('alert');
  expect(watch.queryByText('관심 기업이 없어요.')).toBeNull();
  failed = false;
  await userEvent.click(watch.getByRole('button', { name: '다시 시도' }));
  await watch.findByRole('link', { name: /삼성전자/ });
});
