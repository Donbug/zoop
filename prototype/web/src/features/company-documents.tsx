// 기업 상세 문서 탭(요구 40): 이 기업 사건들의 근거 기사를 중복 없이 최신 발행순으로. 문서마다 연결된 사건과 관계를 적는다.
// 조회 실패는 이 탭만 오류·재시도(요구 54).
import { FileText } from "lucide-react";
import { useCompanyDocuments } from "@/api/queries";
import { DocumentItem, documentRelationLabel } from "@/components/domain/document-item";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import type { DetailRange } from "@/lib/company-timeline";
import { useOverlays } from "./overlays";

export function CompanyDocuments({ companyId, range }: { companyId: string; range?: DetailRange }) {
  const documents = useCompanyDocuments(companyId, range);
  const { openEvidence } = useOverlays();

  if (documents.isPending) return <SkeletonRows count={3} label="근거 문서를 불러오고 있어요" />;
  if (documents.isError) return <ErrorState error={documents.error} title="근거 문서를 불러오지 못했어요" onRetry={() => void documents.refetch()} />;

  const items = documents.data.items;
  if (items.length === 0) return <EmptyState title="이 기업 사건의 근거 문서가 없어요" />;

  return (
    <section aria-labelledby="company-documents-title" className="flex flex-col pt-2">
      <h2 id="company-documents-title" className="flex items-center gap-2 py-2 text-lg font-semibold text-text-primary tabular-nums">
        <FileText className="size-5 text-text-secondary" aria-hidden="true" />
        근거 문서 {items.length}건
      </h2>
      <ol className="flex flex-col divide-y divide-border-subtle">
        {items.map((doc) => (
          <li key={doc.id} className="py-4">
            <DocumentItem
              title={doc.title}
              publisher={doc.publisher}
              url={doc.url}
              publishedAt={doc.publishedAt}
              quotes={doc.quotes.map((q) => ({ id: q.evidenceId, quote: q.quote, quoteVerified: q.quoteVerified }))}
              sentiment={doc.sentiment}
              sentimentName={`${companyId} · ${doc.title ?? "근거 문서"}`}
              analysis={doc}
              synthetic={doc.synthetic}
              onShowEvidence={(summary, evidenceIds) => openEvidence({
                title: doc.title ?? "문서 요약 근거",
                companyId,
                evidenceIds,
                analysisRef: { documentId: summary.documentId, documentVersion: summary.documentVersion, resultVersion: summary.resultVersion },
              })}
              relation={
                <ul className="flex flex-col">
                  {(["REPORTS", "PROVIDES_BACKGROUND", null] as const).map((type) => {
                    const refs = doc.events.filter((e) => e.relationType === type);
                    if (refs.length === 0) return null;
                    // 같은 제목의 사건이 여럿이면(같은 기사에서 나온 서로 다른 사건) 제목은 한 번만 적고 사건 수를 함께 적는다.
                    const titles = [...new Set(refs.map((e) => e.title))];
                    return (
                      <li key={type ?? "other"} className="tabular-nums">
                        {type ? documentRelationLabel[type] : "관련 기사"} · 사건 {refs.length}건:{" "}
                        <span className="text-text-primary">{titles.join(" / ")}</span>
                      </li>
                    );
                  })}
                </ul>
              }
            />
          </li>
        ))}
      </ol>
    </section>
  );
}
