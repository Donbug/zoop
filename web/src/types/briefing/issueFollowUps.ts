import type { CompanyStatement } from './companyOutlook';
import type { IssueIntelligence } from './issueIntelligence';

type Origin = Pick<
  IssueIntelligence,
  'roundId' | 'date' | 'edition' | 'cutoff' | 'resultVersion'
>;

/** Read-only carry list: outcome is not inferred from selection or price. */
export type IssueFollowUps = {
  schemaVersion: 'issue-followups-v1';
  roundId: string;
  baseResultVersion: string;
  cutoff: string;
  scope: 'provided_verified_rounds';
  reviewedRounds: Origin[];
  entries: {
    issueId: string;
    companyId: string;
    title: string;
    companyName: string;
    status: 'outcome_unverified';
    origin: Origin;
    condition: CompanyStatement;
    sources: IssueIntelligence['issues'][number]['sources'][string][];
  }[];
};
