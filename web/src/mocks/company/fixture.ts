import {
  companies,
  directEdges,
  issues,
  mockMember,
} from '@/mocks/graph/fixture';
import type {
  CompanyDetail,
  CompanyDocumentsResponse,
  CompanyMetrics,
  CompanyQuote,
  PortfolioResponse,
  PriceSeries,
  SettingsResponse,
} from '@/types/map/company';

const source = {
  provider: 'yahoo' as const,
  name: 'Yahoo Finance · 개발용 가상 응답',
  official: false,
  delayNote: '15분 지연 예시',
  symbol: '',
  url: null,
};
let watchlist = new Set(mockMember.watchlist);

function requireCompany(id: string) {
  const company = companies.find((item) => item.id === id);
  if (!company) throw new Error('기업을 찾을 수 없습니다.');
  return company;
}

function issueRefs(id: string) {
  return directEdges
    .filter((edge) => edge.target === id)
    .map((edge) => {
      const issue = issues.find((item) => item.id === edge.source)!;
      return {
        issueId: issue.id,
        title: issue.label,
        eventTime: issue.eventTime,
        evidenceCount: issue.evidenceCount ?? 0,
      };
    });
}

export function mockCompany(id: string): CompanyDetail {
  const company = requireCompany(id);
  const refs = issueRefs(id);
  const ticker = id.split(':')[1] ?? null;
  return {
    id,
    name: company.label,
    legalName: null,
    market: id.split(':')[0] ?? null,
    ticker,
    aliases: [company.label, ticker].filter((value): value is string =>
      Boolean(value),
    ),
    sector: id.startsWith('KRX') ? 'IT · 제조' : 'Technology',
    brandColor: company.brandColor,
    logoUrl: company.logoUrl,
    directIssues: refs.slice(0, 3),
    structuralIssues: refs.slice(3, 5),
    holding: mockMember.holdings.includes(id),
    watch: watchlist.has(id),
  };
}

export function mockQuote(id: string): CompanyQuote {
  requireCompany(id);
  const krw = id.startsWith('KRX');
  const price = krw ? 71900 : 187.42;
  return {
    status: 'available',
    companyId: id,
    source: { ...source, symbol: id },
    quote: {
      currency: krw ? 'KRW' : 'USD',
      price,
      asOf: '2026-10-13T15:30:00+09:00',
      previousClose: krw ? 70600 : 184.11,
      change: krw ? 1300 : 3.31,
      changeRate: krw ? 0.0184 : 0.01798,
      dayHigh: krw ? 72400 : 189.2,
      dayLow: krw ? 70400 : 183.8,
      volume: krw ? 18923401 : 46810221,
      fiftyTwoWeekHigh: krw ? 88800 : 212.19,
      fiftyTwoWeekLow: krw ? 51200 : 112.33,
    },
  };
}

export function mockMetrics(id: string): CompanyMetrics {
  const quote = mockQuote(id);
  if (quote.status === 'unavailable') return quote;
  return {
    status: 'available',
    companyId: id,
    source: quote.source,
    asOf: quote.quote.asOf,
    items: [
      {
        code: 'marketValue',
        label: '시가총액',
        value: id.startsWith('KRX') ? '429조 원' : '4,620억 달러',
        basis: null,
      },
      { code: 'per', label: 'PER', value: '18.7배', basis: '최근 12개월' },
      { code: 'pbr', label: 'PBR', value: '1.42배', basis: null },
      {
        code: 'dividendYieldRatio',
        label: '배당수익률',
        value: '2.01%',
        basis: null,
      },
    ],
  };
}

export function mockPrices(id: string): PriceSeries {
  const quote = mockQuote(id);
  if (quote.status === 'unavailable') return quote;
  const base = quote.quote.price;
  return {
    status: 'available',
    companyId: id,
    period: '1m',
    source: quote.source,
    currency: quote.quote.currency,
    interval: '1d',
    points: Array.from({ length: 24 }, (_, index) => ({
      time: new Date(Date.UTC(2026, 8, 20 + index, 6, 30)).toISOString(),
      close:
        Math.round(
          base * (0.91 + index * 0.004 + Math.sin(index) * 0.012) * 100,
        ) / 100,
    })),
  };
}

export function mockPortfolio(): PortfolioResponse {
  return {
    connected: true,
    mockAsOf: '2026-10-13T15:30:00+09:00',
    holdings: mockMember.holdings.map((companyId, index) => {
      const company = requireCompany(companyId);
      const krw = companyId.startsWith('KRX');
      return {
        companyId,
        name: company.label,
        ticker: companyId.split(':')[1] ?? null,
        quantity: [12, 8, 4][index] ?? 1,
        avgPrice: krw ? 68400 : 165.2,
        avgPriceCurrency: krw ? 'KRW' : 'USD',
        marketValue: null,
        weight: null,
      };
    }),
  };
}

export function mockDocuments(id: string): CompanyDocumentsResponse {
  const company = requireCompany(id);
  const refs = issueRefs(id);
  return {
    items: refs.slice(0, 3).map((issue, index) => ({
      id: `mock-document-${id}-${index + 1}`,
      title: `${company.label}, ${issue.title} 관련 소식 (예시)`,
      publisher: index % 2 ? 'MOCK 전자공시' : 'MOCK 경제뉴스',
      url: null,
      publishedAt: `2026-10-${String(13 - index).padStart(2, '0')}T09:00:00+09:00`,
      kind: index % 2 ? 'disclosure' : 'news',
      documentSummary: {
        text: '실제 사실이 아닌 화면 개발용 가상 문서입니다.',
      },
    })),
    nextCursor: null,
  };
}

export function mockSetWatch(id: string, watched: boolean): SettingsResponse {
  requireCompany(id);
  if (watched) watchlist.add(id);
  else watchlist.delete(id);
  return { watchlistIds: [...watchlist], version: 2 };
}

export function resetCompanyMock() {
  watchlist = new Set(mockMember.watchlist);
}
