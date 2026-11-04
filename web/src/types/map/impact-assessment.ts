export type CompanyIssueImpactAssessment = {
  companyId: string;
  issueId: string;
  status: 'available' | 'unavailable';
  reason:
    | 'no_public_path'
    | 'not_recorded'
    | 'not_verified'
    | 'evidence_unavailable'
    | 'issue_impact_not_produced'
    | null;
  results: {
    impactId: string;
    status: 'verified';
    label: 'positive' | 'negative' | 'mixed' | 'undetermined';
    evidenceIds: string[];
    effects: {
      positive: string[];
      negative: string[];
      neutral: string[];
      uncertain: string[];
    };
    provenance: {
      sourceKind: 'collected' | 'synthetic';
      executionMode: 'live' | 'replay';
      recordingKind: 'provider' | 'authored-test';
    };
  }[];
  metadata: {
    source: string;
    asOf: string;
    graphVersion: string | null;
    requestId?: string;
    partial?: boolean;
    failures?: {
      section: string;
      code: string;
      message: string;
      retryable: boolean;
    }[];
  };
};
