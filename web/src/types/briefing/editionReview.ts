import type { BriefingResponse } from './index';
import type { CompanyPrice, CompanyStatement } from './companyOutlook';
export type EditionCompanyCopy = {
  companyId: string;
  stance: 'priority_watch' | 'watch' | 'cautious_watch' | 'deferred';
  title: CompanyStatement;
  takeaway: CompanyStatement;
  newInformation: CompanyStatement;
  judgment: CompanyStatement;
  watch: CompanyStatement[];
  positive: CompanyStatement;
  negative: CompanyStatement;
  checks: {
    condition: string;
    status: 'confirmed' | 'contradicted' | 'not_observed';
    observation: CompanyStatement;
  }[];
};
export type EditionCompanyReview = EditionCompanyCopy & {
  companyName: string;
  role: 'selected' | 'tracked';
  sourceIds: string[];
  previous: EditionCompanyCopy | null;
  price: CompanyPrice;
};
export type EditionReview = {
  schemaVersion: 'zoop-edition-review-v1';
  status: 'REVIEWED';
  verificationMode: 'editorial_source_review';
  reviewer: string;
  reviewedAt: string;
  resultVersion: string;
  roundId: string;
  date: string;
  edition: 'morning' | 'evening';
  cutoff: string;
  analysisVersion: string;
  scopeNote: string;
  previousReview: {
    roundId: string;
    resultVersion: string;
    date: string;
    edition: 'morning' | 'evening';
    cutoff: string;
    draft: { companies: EditionCompanyCopy[] };
  } | null;
  sources: Record<
    string,
    {
      title: string;
      url: string;
      publishedAt: string;
      quote: string;
      fullBody: string;
    }
  >;
  marketVariables: BriefingResponse['marketVariables'];
  capabilities: {
    intraday: 'unavailable';
    sectors: 'unavailable';
    flows: 'unavailable';
    calendar: 'unverified';
  };
  headline: string;
  summary: CompanyStatement;
  marketInterpretation: CompanyStatement;
  comparison: CompanyStatement;
  nextSession: CompanyStatement;
  companies: EditionCompanyReview[];
};
