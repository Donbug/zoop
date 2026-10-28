import type { CompanyStatement } from './companyOutlook';

/** An additive, source-reviewed presentation. Original model results stay intact. */
export type IssueReading = {
  schemaVersion: 'issue-reading-review-v1';
  roundId: string;
  baseResultVersion: string;
  cutoff: string;
  groups: {
    id: string;
    title: string;
    issueIds: string[];
    reason: string;
    support: {
      issueId: string;
      evidenceId: string;
      documentId: string;
      bodySha256: string;
      quote: string;
    }[];
  }[];
  issues: {
    issueId: string;
    whyImportant: CompanyStatement;
    whyNow: CompanyStatement;
    priceUsedForRanking: boolean;
    connections: {
      companyId: string;
      position: 'primary' | 'related' | 'unconfirmed';
      basis: CompanyStatement;
    }[];
  }[];
};
