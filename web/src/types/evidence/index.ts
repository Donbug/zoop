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

// ERD v6 articles/article_versions/evidence and getEvidence response boundary.
export interface EvidenceResponse {
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
  sentiment: DocumentSentiment | null;
  documentVersion: string | null;
  documentSummary: unknown | null;
  analysisStatus: string | null;
  analysisProvenance: {
    sourceKind: 'synthetic' | 'actual';
    executionMode: 'replay' | 'live';
    recordingKind: 'authored-test' | 'provider';
  } | null;
  resultVersion: string | null;
}

export type EvidenceFailureKind = 'permission' | 'unavailable' | 'failed';

export interface EvidenceLoadFailure {
  id: string;
  kind: EvidenceFailureKind;
  message: string;
  retryable: boolean;
}
