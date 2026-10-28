// A-ADM-03: ReviewRuleOut / RuleList / RuleSwitchResponse.
export type PublicationRule = {
  id: string;
  title: string;
  summary: string;
  enabled: boolean;
  defaultEnabled: boolean;
  changedAt: string | null;
  changedBy: string | null;
  reason: string | null;
  eligible: number | null;
  publishedCandidates: number | null;
  publishedEvents: number | null;
  history: {
    id: number;
    enabled: boolean;
    reason: string;
    adminEmail: string;
    changedAt: string;
  }[];
};
export type RuleList = {
  items: PublicationRule[];
  asOf: string;
  nextCursor: string | null;
};
export type RuleSwitchResponse = {
  rule: PublicationRule;
  idempotent: boolean;
  reviewRevision: number;
};
