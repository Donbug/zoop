export interface EvidenceArticle {
  title: string | null;
  publisher: string | null;
  url: string | null;
  publishedAt: string | null;
}

export interface EvidenceMetadata {
  source: string;
  asOf: string;
  graphVersion: string | null;
  requestId: string;
  partial: boolean;
  failures: {
    section: string;
    code: string;
    message: string;
    retryable: boolean;
    asOf?: string | null;
  }[];
}

export type SentimentLabel = 'positive' | 'negative' | 'mixed' | 'undetermined';

export interface DocumentSentiment {
  label: SentimentLabel;
  companyId: string;
  rationale: string;
  quotes: string[];
  judgedAt: string;
  model: string;
  promptVersion: string;
}

export interface AnalysisProvenance {
  sourceKind: 'synthetic' | 'actual';
  executionMode: 'replay' | 'live';
  recordingKind: 'authored-test' | 'provider';
}

export interface AnalysisStageStatus {
  status: 'not_requested' | 'pending' | 'failed' | 'withheld' | 'available';
  reason: string | null;
}

export interface DocumentAnalysisStatus {
  summary: AnalysisStageStatus;
  sentiment: AnalysisStageStatus;
}

export interface DocumentAnalysisSummary {
  schemaVersion: 'zoop-ai-s1-1';
  artifactId: string;
  documentId: string;
  documentVersion: string;
  resultVersion: string;
  text: string;
  claims: {
    claimId: string;
    text: string;
    assertionKind: 'fact' | 'interpretation' | 'limitation';
    evidenceIds: string[];
  }[];
  citations: {
    evidenceId: string;
    documentId: string;
    documentVersion: string;
    textArtifactId: string;
    offsetUnit: 'unicode_code_point';
    start: number;
    end: number;
    quote: string;
    inputKind: 'body' | 'summary';
    rawLocatorIds: string[];
  }[];
  limitations: string[];
  producedAt: string;
  provenance: AnalysisProvenance;
}

/** CompanyDocument와 EvidenceResponse가 공유하는 OpenAPI 문서 분석 계약. */
export interface DocumentAnalysis {
  sentiment?: DocumentSentiment | null;
  documentVersion?: string | null;
  documentSummary?: DocumentAnalysisSummary | null;
  analysisStatus?: DocumentAnalysisStatus | null;
  analysisProvenance?: AnalysisProvenance | null;
  resultVersion?: string | null;
}

// ERD v6 articles/article_versions/evidence and getEvidence response boundary.
export interface EvidenceResponse extends DocumentAnalysis {
  id: string;
  quote: string;
  start: number;
  end: number;
  articleId: string;
  articleVersion: string;
  article: EvidenceArticle | null;
  quoteVerified: boolean | null;
  eventIds: string[];
  metadata: EvidenceMetadata;
}

export type EvidenceFailureKind = 'permission' | 'unavailable' | 'failed';

export interface EvidenceLoadFailure {
  id: string;
  kind: EvidenceFailureKind;
  message: string;
  retryable: boolean;
}
