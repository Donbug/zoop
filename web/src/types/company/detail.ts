import type { ChartPeriod } from './index';
export type Meta = {
  source: string;
  asOf: string;
  graphVersion: string | null;
  partial?: boolean;
  failures?: { section: string; code: string; message: string }[];
};
export type Source = {
  name: string;
  provider: string;
  symbol: string;
  official: boolean;
  delayNote: string | null;
  url: string | null;
};
export type Company = {
  id: string;
  name: string;
  ticker: string | null;
  logoUrl?: string | null;
  legalName: string | null;
  market: string | null;
  sector: string | null;
  representative: string | null;
  foundedDate: string | null;
  websiteUrl: string | null;
  directIssues: unknown[];
  structuralIssues: unknown[];
  summary: {
    summary?: string;
    text?: string;
    status?: string;
    reason?: string;
  } | null;
  metadata: Meta;
};
export type Unavailable = {
  status: 'unavailable';
  reason: string;
  reasonCode?: string;
};
export type Quote =
  | Unavailable
  | {
      status: 'available';
      companyId: string;
      source: Source;
      quote: {
        price: number;
        currency: string;
        asOf: string | null;
        change: number | null;
        changeRate: number | null;
        volume: number | null;
        dayLow: number | null;
        dayHigh: number | null;
        fiftyTwoWeekLow: number | null;
        fiftyTwoWeekHigh: number | null;
      };
    };
export type PricePoint = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
};
export type Prices =
  | Unavailable
  | {
      status: 'available';
      companyId: string;
      period: ChartPeriod;
      source: Source;
      currency: string;
      interval: string;
      points: PricePoint[];
    };
export type Event = {
  id: string;
  title: string;
  eventTime: string | null;
  timePrecision: 'datetime' | 'day' | 'month' | 'year' | 'unknown';
  reportedAt: string | null;
  relationTypes: string[];
  articleCount: number;
  companyIds: string[];
};
export type Events = {
  items: Event[];
  unknownTimeItems: Event[];
  nextCursor: string | null;
  metadata: Meta & { total: number; excludedUnknownTime: number };
};
export type EventDetail = Event & {
  articles: {
    id: string;
    title: string | null;
    publisher: string | null;
    publishedAt: string | null;
    url: string | null;
  }[];
  relations: {
    edgeId: string | null;
    source: string;
    target: string;
    relationType: string;
    evidenceIds: string[];
  }[];
  evidenceIds: string[];
  metadata: Meta;
};
export type Portfolio = {
  connected: boolean;
  holdings: {
    companyId: string;
    quantity: number;
    avgPrice: number;
    avgPriceCurrency: string | null;
    marketValue: number | null;
    weight: number | null;
    quote: { status: string; currency?: string };
  }[];
  mockAsOf: string | null;
  valuation: {
    calculatedAt: string;
    weightUnavailableReason: string | null;
  } | null;
  metadata: Meta;
};
export type Financials = {
  status: 'available' | 'unavailable' | 'failed';
  reason: string | null;
  items: {
    name: string;
    value: number | null;
    unit: string;
    period: string;
    accountingBasis: string | null;
    source: string;
    asOf: string;
  }[];
  metadata: Meta;
};
export type Documents = {
  items: {
    id: string;
    title: string | null;
    publisher: string | null;
    publishedAt: string | null;
    url: string | null;
  }[];
  nextCursor: string | null;
  metadata: Meta;
};
export type Impact = {
  companyId: string;
  issueId: string;
  steps: { id: string; kind: string; reason: string; evidenceIds: string[] }[];
  metadata: Meta;
};
