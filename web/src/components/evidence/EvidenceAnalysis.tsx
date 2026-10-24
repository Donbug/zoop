import type { EvidenceResponse } from '@/types/evidence';
import DocumentSentiment from '@/components/graph/DocumentSentiment';

// D-GRP-05 · gap 31. Port of domain/document-analysis.tsx; saved artifacts only.
export default function EvidenceAnalysis({
  evidence,
}: {
  evidence: EvidenceResponse;
}) {
  if (!evidence.article) return null;
  const summaryStatus = evidence.analysisStatus?.summary.status;
  const sentimentStatus = evidence.analysisStatus?.sentiment.status;
  // 실제 getEvidence는 검증된 저장 요약이 있어도 analysisStatus를 null로 보낸다(EvidenceResponse).
  // 상태가 없으면 아래 스키마·문서/결과 버전·provenance 검사를 거쳐 보이고, 상태가 명시적으로
  // available이 아니면(failed·withheld·not_requested 등) 요약을 쓰지 않는다.
  const stored =
    summaryStatus == null || summaryStatus === 'available'
      ? evidence.documentSummary
      : null;
  const provenance = stored?.provenance ?? evidence.analysisProvenance;
  const authoredReplay =
    provenance?.executionMode === 'replay' &&
    provenance.recordingKind === 'authored-test';
  // EvidenceArticle has no synthetic flag in /api/v1. Authored replay is only
  // eligible for explicitly labelled local MOCK evidence, never actual news.
  if (
    authoredReplay &&
    !(
      import.meta.env.DEV &&
      evidence.metadata.source.startsWith('MOCK') &&
      provenance.sourceKind === 'synthetic'
    )
  )
    return null;
  const summary =
    stored?.schemaVersion === 'zoop-ai-s1-1' &&
    stored.documentId === evidence.articleId &&
    stored.documentVersion === evidence.articleVersion &&
    stored.documentVersion === evidence.documentVersion &&
    stored.resultVersion === evidence.resultVersion
      ? stored
      : null;
  const sentiment =
    !sentimentStatus || sentimentStatus === 'available'
      ? evidence.sentiment
      : null;
  if (
    !summary &&
    !sentiment &&
    ![summaryStatus, sentimentStatus].some(
      (status) => status === 'failed' || status === 'withheld',
    )
  )
    return null;
  const ownCitation = summary?.citations.find(
    (citation) =>
      citation.evidenceId === evidence.id &&
      citation.documentId === evidence.articleId &&
      citation.documentVersion === evidence.articleVersion,
  );
  return (
    <div className="mt-3 flex min-w-0 flex-col gap-2 wrap-anywhere text-zoop-muted">
      {authoredReplay && (summary || sentiment) && (
        <p>데모 예시 · 가상 문서로 만든 AI 분석이에요.</p>
      )}
      {sentiment && (
        <DocumentSentiment
          value={sentiment}
          name={evidence.article.title ?? '근거 문서'}
        />
      )}
      {summary && (
        <section
          aria-label={`${evidence.article.title ?? '근거 문서'} AI 문서 요약`}
          className="flex flex-col gap-2"
        >
          <p className="font-semibold text-zoop-ink">AI 문서 요약</p>
          {summary.claims.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {summary.claims.map((claim) => (
                <li key={claim.claimId}>
                  <p className="leading-relaxed text-zoop-ink">
                    {claim.assertionKind === 'interpretation' && (
                      <span className="text-zoop-muted">해석 · </span>
                    )}
                    {claim.assertionKind === 'limitation' && (
                      <span className="text-zoop-muted">한계 · </span>
                    )}
                    {claim.text}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="leading-relaxed text-zoop-ink">{summary.text}</p>
          )}
          <p>원문을 대체하지 않아요.</p>
        </section>
      )}
      {ownCitation?.inputKind === 'summary' && (
        <p>제공된 요약에서 인용했어요. 기사 전문 인용은 아니에요.</p>
      )}
      {summaryStatus === 'failed' && <p>문서 요약을 만들지 못했어요.</p>}
      {summaryStatus === 'withheld' && <p>문서 요약은 지금 제공하지 않아요.</p>}
      {sentimentStatus === 'failed' && <p>기업별 판정을 만들지 못했어요.</p>}
      {sentimentStatus === 'withheld' && (
        <p>기업별 판정은 지금 제공하지 않아요.</p>
      )}
    </div>
  );
}
