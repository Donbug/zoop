import type { CompanyStatement } from './companyOutlook';
export type AiPriceCompany = {
  companyId: string;
  companyName: string;
  role: 'selected' | 'tracked';
  assessment: 'positive' | 'negative' | 'mixed' | 'watch';
  impact: CompanyStatement;
  outlook: CompanyStatement;
  conditions: CompanyStatement[];
  risks: CompanyStatement[];
  comparison: CompanyStatement & {
    status: 'updated' | 'compared' | 'unavailable';
    previousResultVersion: string | null;
  };
  previous: {
    status: 'available' | 'unavailable';
    kind?: 'verified_ai_price_outlook' | 'preserved_editorial_review';
    roundId?: string;
    resultVersion?: string;
    judgment?: { outlook?: CompanyStatement; judgment?: CompanyStatement };
  };
};
export type AiPriceOutlooks = {
  schemaVersion: 'zoop-ai-price-outlooks-v1';
  model: 'gpt-6-luna';
  promptVersion: 'company-outlook-v5';
  verificationMode: 'independent_model';
  status: 'PASS' | 'WITHHELD';
  roundId: string;
  date: string;
  edition: 'morning' | 'evening';
  cutoff: string;
  resultVersion: string;
  generatedAt: string;
  inputSha256: string;
  reviewVersion: string;
  priceContextVersion: string;
  companies: AiPriceCompany[];
  generationRequestDigest?: string;
  verificationRequestDigest?: string;
  projectionSha256?: string;
  historyNote?: string;
  supersedesResultVersion?: string;
};
