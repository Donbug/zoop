// EvidenceList / EvidenceQuote: 사건·관계의 근거가 되는 원문 인용을 그대로 보여준다. 인용문이 주인공.
// 인용 확인 상태는 아이콘(툴팁·스크린리더 이름)으로, 대조가 필요할 때만 경고 배지 글자를 쓴다.
// 문서 시각은 '발행'으로 적어 관계 확인 시점과 구분한다(요구 24). 원문 링크가 없으면 정해진 안내 문구를 둔다(요구 40).
// 지도에서 연 근거 창이면 인용마다 [지도에서 보기] 토글이 붙어 그 근거가 뒷받침하는 연결선을 지도에서 강조한다(G4).
// 근거 조회가 404(삭제·비공개)·403(볼 권한 없음)이면 다시 시도해도 같으므로 오류가 아니라 상태 한 줄(UnavailableEvidenceNote)로 알리고,
// 그 근거의 내용은 아무것도 그리지 않는다. 일시 장애(5xx·연결 끊김)만 오류 + [다시 시도]다.
import { CheckCircle2, ExternalLink, FileX, Link2Off, Map as MapIcon, TriangleAlert } from "lucide-react";
import { ApiError, type Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { formatKst } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { DocumentAnalysis } from "./document-analysis";

/** 근거(또는 그 근거를 담은 사건)가 지워졌거나 비공개·권한 없음이라 다시 시도해도 받을 수 없는 응답인지 */
export function isEvidenceGone(error: unknown) {
  return error instanceof ApiError && (error.status === 404 || error.status === 403);
}

/** 받을 수 없는 근거 건수만 알린다(오류 표시·다시 시도 없음, 보호 내용 없음). */
export function UnavailableEvidenceNote({ count, className }: { count: number; className?: string }) {
  return (
    <p className={cn("flex items-center gap-2 text-sm text-text-secondary tabular-nums", className)}>
      <FileX className="size-4 shrink-0" aria-hidden="true" />
      근거 {count}건은 삭제됐거나 지금 볼 수 없는 자료예요.
    </p>
  );
}

type Evidence = Pick<Schemas["EvidenceResponse"], "id" | "quote" | "quoteVerified" | "article" | "documentSummary" | "analysisStatus" | "analysisProvenance" | "sentiment" | "documentVersion" | "resultVersion">;

/** 인용 확인 상태. 확인됨은 중성 아이콘 하나, 대조가 필요할 때만 경고 배지. */
export function VerificationBadge({ verified }: { verified: boolean | null }) {
  return verified ? (
    <Tooltip content="원문과 인용이 일치해요">
      <span tabIndex={0} role="img" aria-label="인용 확인됨" className="inline-flex rounded-sm text-text-secondary">
        <CheckCircle2 className="size-4" aria-hidden="true" />
      </span>
    </Tooltip>
  ) : (
    <Badge variant="warning">
      <TriangleAlert aria-hidden="true" />
      원문 대조 필요
    </Badge>
  );
}

/** 인용 ↔ 지도 연동. activeId는 지금 지도에서 강조 중인 근거 id. */
export interface EvidenceMapLink {
  activeId: string | null;
  onToggle: (evidenceId: string) => void;
}

export function EvidenceQuote({ evidence, index, total, mapLink, showAnalysis = true }: { evidence: Evidence; index?: number; total?: number; mapLink?: EvidenceMapLink; showAnalysis?: boolean }) {
  const article = evidence.article;
  const citation = evidence.documentSummary?.citations.find((item) => item.evidenceId === evidence.id);
  const position = index !== undefined ? `인용 문서 ${index + 1}/${total}` : "인용 문서";
  return (
    <article className="flex flex-col gap-2" aria-label={position}>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-secondary">
        <span className="font-medium text-text-primary">{article?.publisher ?? "출처 미상"}</span>
        <span aria-hidden="true">·</span>
        <span>
          발행{" "}
          <time className="tabular-nums" dateTime={article?.publishedAt ?? undefined}>
            {formatKst(article?.publishedAt)}
          </time>
        </span>
        <VerificationBadge verified={evidence.quoteVerified} />
      </p>
      {article?.title && <p className="text-base font-medium text-text-primary">{article.title}</p>}
      {citation?.inputKind === "summary" && <p className="text-sm text-text-secondary">제공된 요약에서 인용했어요. 기사 전문 인용은 아니에요.</p>}
      <blockquote className="bg-surface-sunken px-4 py-3 text-md leading-relaxed text-text-primary">“{evidence.quote}”</blockquote>
      {showAnalysis && <DocumentAnalysis analysis={evidence} synthetic={article?.synthetic === true} name={`${evidence.sentiment?.companyId ? `${evidence.sentiment.companyId} · ` : ""}${article?.title ?? "근거 문서"}`} />}
      <div className="flex flex-wrap items-center gap-x-4">
        {article?.url ? (
          <a
            href={article.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 w-fit items-center gap-1 text-sm font-medium text-brand-primary underline-offset-4 hover:underline"
          >
            <ExternalLink className="size-4" aria-hidden="true" />
            원문 기사 보기
            <span className="sr-only">(새 창에서 열림)</span>
          </a>
        ) : (
          <span className="inline-flex min-h-11 items-center gap-1 text-sm text-text-secondary">
            <Link2Off className="size-4" aria-hidden="true" />
            원문을 제공하지 않는 자료입니다
          </span>
        )}
          {mapLink && (
            <Button
              variant="ghost"
              size="sm"
              aria-pressed={mapLink.activeId === evidence.id}
              onClick={() => mapLink.onToggle(evidence.id)}
              className="aria-pressed:bg-surface-selected aria-pressed:font-semibold"
            >
              <MapIcon aria-hidden="true" />
              지도에서 보기
            </Button>
          )}
      </div>
    </article>
  );
}

export function EvidenceList({ items, mapLink, className }: { items: Evidence[]; mapLink?: EvidenceMapLink; className?: string }) {
  const shownArtifacts = new Set<string>();
  return (
    <ol className={cn("stagger flex flex-col divide-y divide-border-subtle", className)}>
      {items.map((evidence, i) => {
        const artifactId = evidence.documentSummary?.artifactId;
        const showAnalysis = !artifactId || !shownArtifacts.has(artifactId);
        if (artifactId) shownArtifacts.add(artifactId);
        return (
          <li key={evidence.id} className="py-4 first:pt-0 last:pb-0">
            <EvidenceQuote evidence={evidence} index={i} total={items.length} mapLink={mapLink} showAnalysis={showAnalysis} />
          </li>
        );
      })}
    </ol>
  );
}
