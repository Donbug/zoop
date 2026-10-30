import type { CompanyStatement } from './companyOutlook';

/** Optional, separately generated issue-scoped revision. Never an S3/Jev verdict. */
export type IssueIntelligence = {
  schemaVersion: 'issue-intelligence-v1';
  policyVersion: 'issue-selection-policy-v2';
  verificationMode: 'separate_model_request';
  model: 'gpt-6-luna';
  roundId: string;
  date: string;
  edition: 'morning' | 'evening';
  cutoff: string;
  baselineResponseSha256?: string;
  resultVersion: string;
  generatedAt: string;
  issues: {
    issueId: string;
    status: 'PASS';
    resultVersion: string;
    headline: CompanyStatement;
    sources: Record<
      string,
      {
        evidenceId: string;
        documentId: string;
        bodySha256: string;
        title: string;
        url: string;
        publishedAt: string;
        quote: string;
      }
    >;
    companies: {
      companyId: string;
      sourceIds: string[];
      assessment: 'positive' | 'negative' | 'mixed' | 'watch';
      takeaway: CompanyStatement;
      positive: CompanyStatement;
      negative: CompanyStatement;
      newInformation: CompanyStatement;
      impact: CompanyStatement;
      outlook: CompanyStatement;
      conditions: CompanyStatement[];
      risks: CompanyStatement[];
      comparison: CompanyStatement & {
        status: 'updated' | 'compared' | 'unavailable';
        previousResultVersion: string | null;
      };
      previous:
        | { status: 'unavailable'; reason: string }
        | {
            status: 'available';
            issueId: string;
            companyId: string;
            roundId: string;
            date: string;
            edition: 'morning' | 'evening';
            cutoff: string;
            resultVersion: string;
            judgment: { outlook: CompanyStatement };
          };
    }[];
  }[];
};
