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
  }[];
};
