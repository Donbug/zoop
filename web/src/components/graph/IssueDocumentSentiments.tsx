import type { CompanyDocument } from '@/types/map/company';
import DocumentSentiment from './DocumentSentiment';

// D-GRP-03 · gap 25. Retain document identity; never aggregate judgements.
export default function IssueDocumentSentiments({
  documents,
  companyId,
  issueId,
}: {
  documents: CompanyDocument[];
  companyId: string;
  issueId: string;
}) {
  return documents.map((document) => {
    const sentiment = document.sentiment;
    if (
      !sentiment ||
      sentiment.companyId !== companyId ||
      !document.events?.some((event) => event.eventId === issueId) ||
      (document.analysisStatus &&
        document.analysisStatus.sentiment.status !== 'available') ||
      document.analysisProvenance?.recordingKind === 'authored-test'
    )
      return null;
    return (
      <div key={document.id} className="py-2 text-zoop-muted">
        <p>문서 · {document.title ?? '제목 미제공'}</p>
        <DocumentSentiment
          value={sentiment}
          name={document.title ?? '사건 근거 문서'}
        />
        {document.analysisProvenance?.sourceKind === 'synthetic' && (
          <p>합성 테스트 문서 판정이에요.</p>
        )}
      </div>
    );
  });
}
