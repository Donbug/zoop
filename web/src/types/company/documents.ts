import type { Meta } from './detail';
export type Article = {
  title: string | null;
  publisher: string | null;
  publishedAt: string | null;
  url: string | null;
};
export type AnalysisStage = {
  status: 'not_requested' | 'pending' | 'failed' | 'withheld' | 'available';
  reason: string | null;
};
export type DocumentAnalysis = {
  documentVersion?: string | null;
  resultVersion?: string | null;
  documentSummary?: {
    text: string;
    documentId: string;
    documentVersion: string;
    resultVersion: string;
    limitations: string[];
  } | null;
  analysisStatus?: { summary: AnalysisStage; sentiment: AnalysisStage } | null;
  analysisProvenance?: {
    sourceKind: 'synthetic' | 'actual';
    executionMode: 'replay' | 'live';
    recordingKind: 'authored-test' | 'provider';
  } | null;
  sentiment?: {
    companyId: string;
    label: 'positive' | 'negative' | 'mixed' | 'undetermined';
    rationale: string;
    judgedAt: string;
    model: string;
    promptVersion: string;
  } | null;
};
export type CompanyDocument = Article &
  DocumentAnalysis & {
    id: string;
    kind: 'news' | 'disclosure';
    events: {
      eventId: string;
      title: string;
      relationType: 'REPORTS' | 'PROVIDES_BACKGROUND' | null;
    }[];
    quotes: {
      evidenceId: string;
      quote: string;
      quoteVerified: boolean | null;
    }[];
  };
export type CompanyDocuments = {
  items: CompanyDocument[];
  metadata: Meta;
  nextCursor: string | null;
};
export type Evidence = DocumentAnalysis & {
  id: string;
  quote: string;
  start: number;
  end: number;
  articleId: string;
  articleVersion: string;
  article: Article | null;
  quoteVerified: boolean | null;
  eventIds: string[];
  metadata: Meta;
};
