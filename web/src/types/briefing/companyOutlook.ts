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
  generatedAt: string;
  scopeNote: string;
  companies: CompanyOutlook[];
  reason?: string;
};
