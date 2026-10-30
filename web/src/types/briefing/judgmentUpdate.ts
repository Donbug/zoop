import type { CompanyStatement } from './companyOutlook';

export type JudgmentCompany = {
  companyId: string;
  companyName: string;
  role: 'selected' | 'watch';
  decision:
    'initial' | 'maintained' | 'strengthened' | 'weakened' | 'unassessable';
  sourceIds: string[];
  previousJudgment: {
    outlook: CompanyStatement;
    conditions: CompanyStatement[];
  } | null;
  previousResultVersion: string | null;
  newEvidence: CompanyStatement;
  reason: CompanyStatement;
  strengthenIf: CompanyStatement;
  weakenIf: CompanyStatement;
  topic: CompanyStatement;
  title: CompanyStatement;
  description: CompanyStatement;
};
export type JudgmentUpdate = {
  schemaVersion: 'zoop-judgment-update-v1';
  status: 'PASS' | 'WITHHELD';
  roundId: string;
  edition: 'morning' | 'evening';
  cutoff: string;
  previousRoundId: string;
  previousCutoff: string;
  companyResultVersion: string;
  previousResultVersion: string;
  resultVersion: string;
  scopeNote: string;
  conclusion?: CompanyStatement;
  industryChange?: CompanyStatement;
  limits?: CompanyStatement;
  companies?: JudgmentCompany[];
  sources?: Record<
    string,
    {
      evidenceId: string;
      title: string;
      url: string;
      fullBody?: string;
      publishedAt: string;
    }
  >;
  editorialReview?: {
    reviewer: string;
    reviewedAt: string;
    modelVerificationAppliesTo: 'pre_edit_draft';
    reason: string;
  };
  reason?: string;
};
