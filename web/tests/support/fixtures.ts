import type { MemberSettings } from '@/types/settings';
import type { CompanySummary } from '@/types/company';
import type {
  Holding,
  MockPortfolioOption,
  Portfolio,
} from '@/types/portfolio';

export const metadata = {
  source: 'test',
  asOf: '2026-10-12T00:00:00Z',
  graphVersion: null,
  requestId: 'req-test',
  partial: false,
  failures: [],
};

/** SettingsResponse 본문(목표 계약 그대로, ApiResponse 래퍼 없음) */
export function settingsBody(
  overrides: Partial<MemberSettings> = {},
): MemberSettings & { metadata: typeof metadata } {
  return {
    mode: 'watchlist',
    watchlistIds: [],
    tutorialCompleted: false,
    completed: false,
    investor: null,
    version: 1,
    ...overrides,
    metadata,
  };
}

export const MOCK_OPTIONS: MockPortfolioOption[] = [
  {
    id: 'mock-1',
    label: '성장주 계좌',
    accountId: 'MOCK-0001',
    holdingsCount: 3,
  },
  {
    id: 'mock-2',
    label: '배당주 계좌',
    accountId: 'MOCK-0002',
    holdingsCount: 1,
  },
];

/** MockPortfolioListResponse 본문 */
export function mockPortfoliosBody(items = MOCK_OPTIONS) {
  return { items, nextCursor: null, metadata };
}

export const SAMSUNG_HOLDING: Holding = {
  companyId: 'cmp-samsung',
  name: '삼성전자',
  ticker: '005930',
  quantity: 20,
  avgPrice: 250000,
  avgPriceCurrency: 'KRW',
  quote: {
    status: 'available',
    price: 271500,
    currency: 'KRW',
    asOf: '2026-10-06T03:41:00Z',
    sourceName: 'test',
  },
  marketValue: 5430000,
  weight: null,
};

/** PortfolioResponse 본문: 연결 안 됨 */
export function disconnectedPortfolioBody() {
  return {
    connected: false,
    connection: null,
    holdings: [],
    mockAsOf: null,
    valuation: null,
    metadata,
  } satisfies Portfolio & { metadata: unknown };
}

/** PortfolioResponse 본문: 연결됨 */
export function connectedPortfolioBody(
  holdings: Holding[] = [SAMSUNG_HOLDING],
  label = '배당주 계좌',
) {
  return {
    connected: true,
    connection: {
      id: 'conn-1',
      mockPortfolioId: 'mock-2',
      label,
      connectedAt: '2026-10-06T03:00:00Z',
      accountId: 'MOCK-0002',
      cash: { amount: 3000000, currency: 'KRW' },
      status: 'connected',
    },
    holdings,
    mockAsOf: '2026-10-01T11:33:00Z',
    valuation: {
      calculatedAt: '2026-10-06T03:41:00Z',
      currency: 'KRW',
      totalMarketValue: 5430000,
      weightStatus: 'unavailable',
      weightUnavailableCode: 'mixed_currency',
      weightUnavailableReason:
        '보유 종목의 시세 통화가 서로 달라요. 환율로 바꾸지 않아 합계와 비중을 계산하지 않았어요.',
    },
    metadata,
  } satisfies Portfolio & { metadata: unknown };
}

/** ConnectionResponse 본문 */
export function connectionBody(mockPortfolioId = 'mock-2') {
  const option = MOCK_OPTIONS.find((item) => item.id === mockPortfolioId);
  return {
    id: 'conn-1',
    mockPortfolioId,
    label: option?.label ?? '가상 계좌',
    connectedAt: '2026-10-06T03:00:00Z',
    accountId: option?.accountId ?? null,
    cash: { amount: 3000000, currency: 'KRW' },
    status: 'connected',
    holdingsCount: option?.holdingsCount ?? 0,
    metadata,
  };
}

export function companySummary(
  id: string,
  name: string,
  ticker: string | null,
  issueCount: number,
): CompanySummary {
  return {
    id,
    name,
    ticker,
    aliases: [],
    sector: null,
    brandColor: null,
    logoUrl: null,
    issueCount,
  };
}

export const SAMSUNG = companySummary('cmp-samsung', '삼성전자', '005930', 27);
export const SAMSUNG_SDI = companySummary('cmp-sdi', '삼성SDI', '006400', 6);
export const NVIDIA = companySummary('cmp-nvidia', 'NVIDIA', 'NVDA', 46);

/** CompanyListResponse 본문 */
export function companyListBody(items: CompanySummary[]) {
  return { items, nextCursor: null, metadata };
}

/** CompanyDetail 본문 중 화면이 읽는 값(승인된 사건은 issueCount만큼 만든다) */
export function companyDetailBody(company: CompanySummary) {
  return {
    ...company,
    legalName: company.name,
    market: null,
    representative: null,
    foundedDate: null,
    websiteUrl: null,
    directIssues: Array.from({ length: company.issueCount }, (_, index) => ({
      issueId: `${company.id}-issue-${index}`,
      title: `사건 ${index}`,
    })),
    structuralIssues: [],
    summary: null,
    holding: null,
    watch: null,
    metadata,
  };
}
