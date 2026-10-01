// EvidenceList / EvidenceQuote: 사건·관계의 근거가 되는 원문 인용을 그대로 보여준다. 인용문이 주인공.
// 인용 확인 상태는 아이콘(툴팁·스크린리더 이름)으로, 대조가 필요할 때만 경고 배지 글자를 쓴다.
// 문서 시각은 '발행'으로 적어 관계 확인 시점과 구분한다(요구 24). 원문 링크가 없으면 정해진 안내 문구를 둔다(요구 40).
// 지도에서 연 근거 창이면 인용마다 [지도에서 보기] 토글이 붙어 그 근거가 뒷받침하는 연결선을 지도에서 강조한다(G4).
import { CheckCircle2, ExternalLink, Link2Off, Map as MapIcon, TriangleAlert } from "lucide-react";
import type { Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { formatKst } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Evidence = Pick<Schemas["EvidenceResponse"], "id" | "quote" | "quoteVerified" | "article">;

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

export function EvidenceQuote({ evidence, index, total, mapLink }: { evidence: Evidence; index?: number; total?: number; mapLink?: EvidenceMapLink }) {
  const article = evidence.article;
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
      <blockquote className="bg-surface-sunken px-4 py-3 text-md leading-relaxed text-text-primary">“{evidence.quote}”</blockquote>
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
  return (
    <ol className={cn("stagger flex flex-col divide-y divide-border-subtle", className)}>
      {items.map((evidence, i) => (
        <li key={evidence.id} className="py-4 first:pt-0 last:pb-0">
          <EvidenceQuote evidence={evidence} index={i} total={items.length} mapLink={mapLink} />
        </li>
      ))}
    </ol>
  );
}
