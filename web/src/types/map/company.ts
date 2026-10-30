import type { TimePrecision } from './event';
export type SourceInfo = {
  provider: 'toss' | 'yahoo' | 'naver';
  name: string;
  official: boolean;
  delayNote: string | null;
  symbol: string;
  url: string | null;
};

export type CompanyIssue = {
  issueId: string;
  title: string;
  eventTime: string | null;
  /** API CompanyIssueRef.timePrecision. 예전 응답·mock에는 없을 수 있다. */
  timePrecision?: TimePrecision | null;
  evidenceCount: number;
};

export type CompanyDetail = {
  id: string;
  name: string;
  legalName: string | null;
  market: string | null;
  ticker: string | null;
  aliases: string[];
  sector: string | null;
  brandColor: string | null;
  logoUrl: string | null;
  directIssues: CompanyIssue[];
  structuralIssues: CompanyIssue[];
  holding: boolean | null;
  watch: boolean | null;
};

export type Unavailable = {
  status: 'unavailable';
  companyId: string;
  reasonCode: 'not_connected' | 'unsupported_symbol' | 'no_data';
  reason: string;
};

export type CompanyQuote =
  | Unavailable
  | {
      status: 'available';
      companyId: string;
      source: SourceInfo;
      quote: {
        currency: string;
        price: number;
        asOf: string | null;
        previousClose: number | null;
        change: number | null;
        changeRate: number | null;
        dayHigh: number | null;
        dayLow: number | null;
        volume: number | null;
        fiftyTwoWeekHigh: number | null;
        fiftyTwoWeekLow: number | null;
      };
    };

export type CompanyMetrics =
  | Unavailable
  | {
      status: 'available';
      companyId: string;
      source: SourceInfo;
      asOf: string | null;
      items: {
        code: string;
        label: string;
        value: string;
        basis: string | null;
      }[];
    };

export type PriceSeries =
  | Unavailable
  | {
      status: 'available';
      companyId: string;
      period: '1m';
      source: SourceInfo;
      currency: string;
      interval: '1d';
      points: { time: string; close: number }[];
    };

export type PortfolioHolding = {
  companyId: string;
  name: string;
  ticker: string | null;
  quantity: number;
  avgPrice: number;
  avgPriceCurrency: string | null;
  marketValue: number | null;
  weight: number | null;
};

export type PortfolioResponse = {
  connected: boolean;
  holdings: PortfolioHolding[];
  mockAsOf: string | null;
};

export type CompanyDocument = {
  id: string;
  title: string | null;
  publisher: string | null;
  url: string | null;
  publishedAt: string | null;
  kind: 'news' | 'disclosure';
  documentSummary?: { text?: string } | null;
  /** getCompanyDocuments; absent on older/local fixtures, never inferred. */
  events?: { eventId: string; title: string; relationType: string | null }[];
  sentiment?: import('@/types/evidence').DocumentSentiment | null;
  analysisStatus?: import('@/types/evidence').DocumentAnalysisStatus | null;
  analysisProvenance?: import('@/types/evidence').AnalysisProvenance | null;
};

export type CompanyDocumentsResponse = {
  items: CompanyDocument[];
  nextCursor: string | null;
};

export type SettingsResponse = {
  watchlistIds: string[];
  version: number;
};

export type CompanyPanelData = {
  company: CompanyDetail;
  quote: CompanyQuote;
  metrics: CompanyMetrics;
  prices: PriceSeries;
  documents: CompanyDocumentsResponse;
  holding: PortfolioHolding | null;
};
