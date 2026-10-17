import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createFakeServer, json, type FakeServer } from '../support/fakeServer';

// 실제 API 모드(VITE_GRAPH_DATA_SOURCE=api): 목표 계약의 응답은 ApiResponse로 감싸지 않은 본문이다.
// usesCompanyMock은 모듈을 읽을 때 정해지므로 환경을 바꾼 뒤 다시 불러온다.
async function loadApi() {
  vi.stubEnv('VITE_GRAPH_DATA_SOURCE', 'api');
  vi.resetModules();
  return import('@/apis/graph/companies');
}

const quote = {
  companyId: 'KRX:005930',
  status: 'available',
  source: 'toss',
  quote: {
    price: 71200,
    change: 900,
    changeRate: 0.0128,
    currency: 'KRW',
    asOf: '2026-10-16T06:30:00Z',
    fiftyTwoWeekHigh: 88800,
    fiftyTwoWeekLow: 51200,
  },
};

describe('기업 패널 API는 감싸지 않은 응답 본문을 그대로 쓴다', () => {
  let server: FakeServer;

  beforeEach(() => {
    server = createFakeServer();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('시세·지표·기업 상세를 본문 그대로 돌려준다', async () => {
    const api = await loadApi();
    expect(api.usesCompanyMock).toBe(false);
    const metrics = {
      companyId: 'KRX:005930',
      status: 'unavailable',
      reasonCode: 'not_connected',
      reason: '지표 공급자가 연결되지 않았어요.',
    };
    const company = { id: 'KRX:005930', name: '삼성전자', directIssues: [] };
    server.on('GET', '/api/v1/companies/:id/quote', () => json(quote));
    server.on('GET', '/api/v1/companies/:id/metrics', () => json(metrics));
    server.on('GET', '/api/v1/companies/:id', () => json(company));

    const read = await api.getCompanyQuote('KRX:005930');
    expect(read).toEqual(quote);
    expect(read.status === 'available' && read.quote.fiftyTwoWeekHigh).toBe(
      88800,
    );
    expect(await api.getCompanyMetrics('KRX:005930')).toEqual(metrics);
    expect(await api.getCompany('KRX:005930')).toEqual(company);
  });

  it('보유 종목과 관심 종목 저장도 본문 그대로 돌려준다', async () => {
    const api = await loadApi();
    // 모듈을 다시 불러왔으므로 같은 인스턴스의 저장소에 세션을 넣는다.
    const { useAuthStore } = await import('@/stores/useAuthStore');
    useAuthStore.getState().setSession({
      authenticated: true,
      kind: 'member',
      user: { id: 'mem-1', email: 'member@zoop.test', displayName: '회원' },
      setup: { completed: true, tutorialCompleted: true },
      csrfToken: 'csrf-member',
      expiresAt: null,
    });
    const portfolio = { connected: false, holdings: [], mockAsOf: null };
    const settings = { watchlistIds: ['KRX:005930'], version: 3 };
    server.on('GET', '/api/v1/portfolio', () => json(portfolio));
    server.on('PUT', '/api/v1/me/watchlist/:id', () => json(settings));

    expect(await api.getPortfolio()).toEqual(portfolio);
    expect(await api.setWatchlistCompany('KRX:005930', true)).toEqual(settings);
    expect(server.calls('PUT', '/api/v1/me/watchlist/:id')[0].body).toEqual({
      watched: true,
    });
  });
});
