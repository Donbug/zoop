import type { BriefingEdition } from './index';

export type MarketOutlookDirection = 'up' | 'down' | 'flat' | 'uncertain';
export type MarketOutlookClaim = {
  claimId: string;
  kind:
    | 'fact'
    | 'interpretation'
    | 'forecast'
    | 'forecast_update'
    | 'result_comparison';
  text: string;
  evidenceIds: string[];
  indicatorIds: string[];
  previousPublicationIds: string[];
  previousForecastIds: string[];
  evaluationIds: string[];
  targetId: string | null;
  direction: MarketOutlookDirection | null;
  conditions: string[];
  counterFactors: string[];
  updateAction: 'maintain' | 'strengthen' | 'weaken' | 'withdraw' | null;
};
export type MarketOutlookTarget = {
  targetId: string;
  indicatorId: 'kospi' | 'kosdaq';
  valueKind: 'close';
  baselineDate: string;
  baselineValue: number;
  targetDate: string;
  targetEnd: string;
  calendarRef: string;
  rule: 'close_vs_baseline_v1';
};
export type MarketOutlookAnalysis = {
  schemaVersion: 'zoop-market-outlook-analysis-v1';
  edition: BriefingEdition;
  cutoff: string;
  mode: 'morning_update' | 'evening_review';
  previousPublication: {
    status: 'available' | 'unavailable';
    kind: string;
    roundId?: string;
    date?: string;
    edition?: BriefingEdition;
    cutoff?: string;
    resultVersion?: string;
    reason?: string;
  };
  coverage: {
    documents: number;
    newDocuments: number;
    backgroundDocuments: number;
    companyNames: string[];
    marketRepresentative: false;
    sectorPriceFeedAvailable: false;
  };
  claims: MarketOutlookClaim[];
  forecasts: {
    forecastId: string;
    target: MarketOutlookTarget;
    text: string;
    direction: MarketOutlookDirection;
    conditions: string[];
    counterFactors: string[];
    evidenceIds: string[];
    indicatorIds: string[];
  }[];
  forecastEvaluations: {
    evaluationId: string;
    forecastId: string;
    target: MarketOutlookTarget;
    rule: 'close_vs_baseline_v1';
    status: 'evaluated' | 'unavailable';
    reason: string | null;
    actualValue: number | null;
    actualDirection: MarketOutlookDirection | null;
    directionMatched: boolean | null;
  }[];
  scopeNote: string;
};
