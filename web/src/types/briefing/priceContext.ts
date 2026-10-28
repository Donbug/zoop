import type { CompanyStatement } from './companyOutlook';
export type PriceAwareOutlook = CompanyStatement & {
  schemaVersion: 'zoop-company-price-outlook-v1';
  authorship: 'source_bound_composition';
  stance: string;
  businessJudgment: CompanyStatement;
  priceObservation: string;
  nextCheck: string;
  takeaway: string;
  marketNote: string;
};
export type PriceMarketReference = {
  status: 'available' | 'unavailable';
  snapshotSha256: string;
  indicators: {
    id: 'kospi' | 'kosdaq' | 'usdkrw';
    label: string;
    value: number;
    unit: string;
    valueKind: string;
    observedDate: string;
    observedAt: string | null;
    status: 'ok' | 'delayed';
    source: {
      name: string;
      url: string;
      official: boolean;
      delayNote?: string | null;
    };
    baselineDate: string | null;
    changeRatePercent: string | null;
    text: string;
  }[];
  note: string;
};
export type PricePoint = {
  value: string;
  observedAt: string;
  kind: 'daily_close' | 'five_minute_close';
};
export type PriceNewsObservation = {
  evidenceId: string;
  publishedAt: string;
  timing: 'before_session' | 'during_session' | 'after_session';
  status: 'observed' | 'no_post_news_trade' | 'event_window_unavailable';
  postNewsBars: number;
  before: PricePoint | null;
  changeRatePercent: string | null;
  observation: string;
};
type Base = {
  companyId: string;
  companyName: string;
  currency: 'KRW' | 'USD';
  provider: 'toss';
  cutoff: string;
  responseSha256s: string[];
  outlook?: PriceAwareOutlook;
};
export type CompanyPriceContext = Base &
  (
    | { status: 'unavailable'; reason: string }
    | {
        status: 'available';
        sessionDate: string;
        exchangeTimezone: string;
        completeSession: boolean;
        barCount: number;
        latest: PricePoint;
        day: {
          baselineDate: string | null;
          baselineClose: string | null;
          changeRatePercent: string | null;
          kind: 'provider_daily_bar' | 'completed_five_minute_bars';
          open: string;
          high: string;
          low: string;
          closeOrLast: string;
          volume: string | null;
          from: string;
          to: string;
        };
        summary: string;
        flow: string;
        news: PriceNewsObservation[];
        sinceMorning: {
          status:
            | 'available'
            | 'unavailable'
            | 'no_new_session'
            | 'revised_observation';
          observation: string;
          before?: PricePoint;
          changeRatePercent?: string;
        };
        interpretation: string;
        limitation: string;
      }
  );
export type BriefingPriceContext = {
  schemaVersion: 'zoop-company-price-context-v1';
  status: 'derived';
  roundId: string;
  date: string;
  edition: 'morning' | 'evening';
  cutoff: string;
  reviewVersion: string;
  resultVersion: string;
  generatedAt: string;
  authorship: 'deterministic_price_observation';
  scopeNote: string;
  outlookIntegrationVersion?: 'zoop-company-price-outlook-v1';
  marketReference?: PriceMarketReference;
  companies: CompanyPriceContext[];
};
