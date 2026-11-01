/** D-BRF-01/02, FS036: selection projection; never a replacement published payload. */
export type PersonalIssue = {
  issueId: string;
  title: string;
  importance: number;
  whyImportant: string;
  whyNow: string;
  analysis: string | null;
  nextCheck: string | null;
  matches: {
    companyId: string;
    name: string;
    reason: string;
    directness: 'direct' | 'indirect';
    kinds: ('holding' | 'watchlist')[];
  }[];
  sources: {
    evidenceId: string;
    quote: string;
    url: string;
    publishedAt: string;
  }[];
};
export type PersonalBriefingSelection = {
  roundId: string;
  edition?: 'morning' | 'evening';
  dataAsOf: string;
  policyVersion: string;
  basisObservedAt: string;
  basis: { holdings: string[]; watchlist: string[]; holdingsKind: string };
  poolVersion: string | null;
  scope?: string;
  status:
    | 'available'
    | 'no_companies'
    | 'pool_unavailable'
    | 'no_matching_issues'
    | 'sources_unavailable';
  message: string | null;
  aiAnalysis?: PersonalAiAnalysis;
  eligibleCount: number;
  matchingCount: number;
  excludedByCurrentAccess: number;
  items: PersonalIssue[];
  trackingStatus?: string;
  previousRoundId: string | null;
  tracking: {
    issueId: string;
    title: string;
    companyId: string;
    companyName: string;
    status: 'not_observed' | 'follow_up_available';
    message: string;
    nextCheck: string | null;
    basis: string;
    personalAiNextCheck?: string;
    personalAiResultVersion?: string;
  }[];
};

export type PersonalAiStatement = { text: string; evidenceIds: string[] };
export type PersonalAiCompany = {
  direction: 'positive' | 'negative' | 'mixed' | 'watch';
  keyPoint: PersonalAiStatement;
  confirmedFact: PersonalAiStatement;
  businessImpact: PersonalAiStatement;
  forMyStocks: PersonalAiStatement;
  priceObservation: PersonalAiStatement | null;
  previousChange: PersonalAiStatement & {
    status: 'unavailable' | 'maintained' | 'strengthened' | 'weakened';
  };
  nextCheck: PersonalAiStatement;
};
export type PersonalAiAnalysis =
  | { status: 'unavailable'; reason: string }
  | {
      status: 'available';
      roundId: string;
      cutoff: string;
      model: string;
      promptVersion: string;
      resultVersion: string;
      generatedAt: string;
      verificationMode: 'separate_request_same_model';
      draft: {
        overview: PersonalAiStatement;
        issues: Record<
          string,
          { companies: Record<string, PersonalAiCompany> }
        >;
      };
    };
