import type { Meta } from './detail';
import type {
  DocumentAnalysis,
  DocumentSentiment,
  EvidenceArticle,
  EvidenceResponse,
} from '@/types/evidence';

export type Article = EvidenceArticle;
export type CompanyDocument = Article &
  DocumentAnalysis & {
    id: string;
    kind: 'news' | 'disclosure';
    sentiment: DocumentSentiment | null;
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
export type Evidence = EvidenceResponse;
