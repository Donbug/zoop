import type { MemberSettings } from '@/types/settings';
import {
  companyDetailBody,
  companyListBody,
  connectedPortfolioBody,
  connectionBody,
  disconnectedPortfolioBody,
  mockPortfoliosBody,
  NVIDIA,
  SAMSUNG,
  SAMSUNG_SDI,
  settingsBody,
} from './fixtures';
import { json, noContent, type FakeServer } from './fakeServer';

const COMPANIES = [SAMSUNG, SAMSUNG_SDI, NVIDIA];

/**
 * 초기 설정을 마친 회원의 가짜 서버 상태.
 * 관심 종목 저장·계좌 연결·해제가 이후 조회에 반영된다.
 */
export function myMember(
  server: FakeServer,
  {
    connected = false,
    watchlistIds = [],
  }: { connected?: boolean; watchlistIds?: string[] } = {},
) {
  const state = {
    connected,
    settings: settingsBody({
      completed: true,
      investor: connected,
      watchlistIds,
    }) as MemberSettings,
  };

  server.on('GET', '/api/v1/me/settings', () =>
    json(settingsBody(state.settings)),
  );
  server.on('PUT', '/api/v1/me/watchlist/:id', ({ params, body }) => {
    const { watched } = body as { watched: boolean };
    const rest = state.settings.watchlistIds.filter((id) => id !== params.id);
    state.settings = {
      ...state.settings,
      watchlistIds: watched ? [...rest, params.id] : rest,
      version: state.settings.version + 1,
    };
    return json(settingsBody(state.settings));
  });
  server.on('GET', '/api/v1/portfolio', () =>
    json(
      state.connected ? connectedPortfolioBody() : disconnectedPortfolioBody(),
    ),
  );
  server.on('GET', '/api/v1/portfolio/mock-portfolios', () =>
    json(mockPortfoliosBody()),
  );
  server.on('POST', '/api/v1/portfolio/connections', ({ body }) => {
    state.connected = true;
    return json(
      connectionBody((body as { mockPortfolioId: string }).mockPortfolioId),
      201,
    );
  });
  server.on('DELETE', '/api/v1/portfolio/connections/:id', () => {
    state.connected = false;
    return noContent();
  });
  server.on('GET', '/api/v1/companies', ({ query }) => {
    const q = query.get('q') ?? '';
    return json(
      companyListBody(
        COMPANIES.filter(
          (company) => company.name.includes(q) || company.ticker === q,
        ),
      ),
    );
  });
  server.on('GET', '/api/v1/companies/:id', ({ params }) => {
    const company = COMPANIES.find((item) => item.id === params.id);
    return company
      ? json(companyDetailBody(company))
      : json({ error: { code: 'RESOURCE_NOT_FOUND' } }, 404);
  });

  return state;
}
