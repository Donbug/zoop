export type CompanyStatement = { text: string; evidenceIds: string[] };
export type CompanyOutlook = {
  companyId: string;
  companyName: string;
  issueIds: string[];
  facts: CompanyStatement[];
  assessment: 'positive' | 'negative' | 'mixed' | 'watch';
  impact: CompanyStatement;
  outlook: CompanyStatement;
  conditions: CompanyStatement[];
  risks: CompanyStatement[];
  comparison: CompanyStatement & {
    status: 'updated' | 'compared' | 'unavailable';
    previousResultVersion: string | null;
  };
  reading?: {
    status: 'PASS' | 'WITHHELD';
    resultVersion: string;
    schemaVersion?: 'zoop-company-reading-v2';
    fact?: CompanyStatement;
    background?: CompanyStatement;
    brief?: CompanyStatement;
    watch?: CompanyStatement;
    change?: CompanyStatement;
  };
  card?: {
    schemaVersion: 'zoop-company-card-v1';
    status: 'PASS' | 'WITHHELD';
    resultVersion: string;
    topic?: CompanyStatement;
    title?: CompanyStatement;
    description?: CompanyStatement;
  };
  price?: CompanyPrice;
  previous?: {
    status: 'available' | 'unavailable';
    cutoff?: string;
    resultVersion?: string;
    judgment?: { outlook: CompanyStatement };
  };
  observedMovement: { status: 'unavailable'; reason: string };
  sources: {
    evidenceId: string;
    documentId: string;
    documentVersion: string;
    bodySha256: string;
    quote: string;
    title: string;
    url: string;
    publishedAt: string;
  }[];
};
export type CompanyOutlooks = {
  schemaVersion: 'zoop-company-outlooks-v1';
  roundId: string;
  edition: 'morning' | 'evening';
  cutoff: string;
  status: 'PASS' | 'WITHHELD';
  resultVersion: string;
  priceVersion?: string;
  generatedAt: string;
  scopeNote: string;
  companies: CompanyOutlook[];
  reason?: string;
};

export type CompanyPricePoint = {
  value: string;
  observedAt: string;
  sessionDate: string;
  kind: 'five_minute_close' | 'daily_close';
};
export type CompanyPrice = {
  companyId: string;
  cutoff: string;
  currency: 'KRW' | 'USD';
  exchangeTimezone: string;
  source: string;
  official: boolean;
  note: string;
  status: 'available' | 'unavailable';
  reason: string | null;
  latest: CompanyPricePoint | null;
  baseline: CompanyPricePoint | null;
  baselineKind?: 'morning_cutoff' | 'previous_close';
  comparisonStatus: 'available' | 'unavailable' | 'no_new_session';
  change: string | null;
  changeRate: string | null;
  sources: {
    interval: string;
    url: string;
    collectedAt: string;
    period1?: number;
    period2?: number;
  }[];
};
