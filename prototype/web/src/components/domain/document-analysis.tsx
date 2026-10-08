// 저장된 문서 분석만 표시한다. 조회·팝오버·근거 열기는 분석 실행 경로가 아니다.
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { AiBadge } from "./ai";
import { SentimentLabel } from "./status-labels";

interface DocumentAnalysisProps {
  analysis: Pick<Schemas["CompanyDocument"], "documentSummary" | "analysisStatus" | "analysisProvenance" | "sentiment" | "documentVersion" | "resultVersion">;
  synthetic: boolean;
  name: string;
  onShowEvidence?: (summary: Schemas["AnalysisSummary"], evidenceIds: string[]) => void;
}

/** 미요청·미판정에는 빈 자리를 만들지 않는다. 실패·제공 중단은 결과 본문 없이 알린다. */
export function DocumentAnalysis({ analysis, synthetic, name, onShowEvidence }: DocumentAnalysisProps) {
  const summaryStatus = analysis.analysisStatus?.summary.status;
  const sentimentStatus = analysis.analysisStatus?.sentiment.status;
  const summary = summaryStatus === "available" ? analysis.documentSummary : null;
  const provenance = summary?.provenance ?? analysis.analysisProvenance;
  const authoredReplay = provenance?.executionMode === "replay" && provenance.recordingKind === "authored-test";
  // 서버 gate와 별개로 실제 기사에 합성 판정이 붙는 화면은 만들지 않는다.
  if (authoredReplay && (!synthetic || provenance.sourceKind !== "synthetic")) return null;
  const sentiment = !sentimentStatus || sentimentStatus === "available" ? analysis.sentiment : null;
  if (!summary && !sentiment && ![summaryStatus, sentimentStatus].some((status) => status === "failed" || status === "withheld")) return null;
  return (
    <div className="flex min-w-0 flex-col gap-2 break-words">
      {authoredReplay && (summary || sentiment) && <p className="text-sm text-text-secondary">데모 예시 · 가상 문서로 만든 AI 분석이에요.</p>}
      <SentimentLabel judgement={sentiment} accessibleName={name} />
      {summary && (
        <section aria-label={`${name} AI 문서 요약`} className="flex flex-col gap-2">
          <div><AiBadge label="AI 문서 요약" /></div>
          {summary.claims.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {summary.claims.map((claim, index) => (
                <li key={claim.claimId}>
                  <p className="text-base leading-relaxed text-text-primary">
                    {claim.assertionKind === "interpretation" && <span className="text-sm text-text-secondary">해석 · </span>}
                    {claim.assertionKind === "limitation" && <span className="text-sm text-text-secondary">한계 · </span>}
                    {claim.text}
                  </p>
                  {onShowEvidence && claim.evidenceIds.length > 0 && (
                    <Button variant="link" size="sm" aria-label={`요약 ${index + 1} 근거 보기`} onClick={() => onShowEvidence(summary, claim.evidenceIds)}>
                      근거 {claim.evidenceIds.length}건 보기
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          ) : <p className="text-base leading-relaxed text-text-primary">{summary.text}</p>}
          <p className="text-sm text-text-secondary">원문을 대체하지 않아요.</p>
        </section>
      )}
      {summaryStatus === "failed" && <p className="text-sm text-text-secondary">문서 요약을 만들지 못했어요.</p>}
      {summaryStatus === "withheld" && <p className="text-sm text-text-secondary">문서 요약은 지금 제공하지 않아요.</p>}
      {sentimentStatus === "failed" && <p className="text-sm text-text-secondary">기업별 판정을 만들지 못했어요.</p>}
      {sentimentStatus === "withheld" && <p className="text-sm text-text-secondary">기업별 판정은 지금 제공하지 않아요.</p>}
    </div>
  );
}
