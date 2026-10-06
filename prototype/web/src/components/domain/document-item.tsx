// DocumentItem: 근거 문서(뉴스·공시) 한 건. 출처 · 발행 시각 → 제목 → 관련 설명 → 저장한 인용 → 원문 링크(요구 40).
// 인용과 출처는 저장해 둔 값이라 원문 사이트에 닿지 못해도 그대로 보인다. 원문 링크가 없으면 정해진 안내 문구를 둔다.
import { ExternalLink, Link2Off } from "lucide-react";
import type { ReactNode } from "react";
import { formatKst } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { VerificationBadge } from "./evidence";
import { SentimentLabel, type SentimentJudgement } from "./status-labels";

export interface DocumentQuoteItem {
  id: string;
  quote: string;
  quoteVerified: boolean | null;
}

export type DocumentRelation = "REPORTS" | "PROVIDES_BACKGROUND" | null;

/** 문서가 사건과 맺은 관계를 쉬운 말로. 모르면 아무것도 쓰지 않는다. */
export const documentRelationLabel: Record<Exclude<DocumentRelation, null>, string> = {
  REPORTS: "사건을 보도한 기사",
  PROVIDES_BACKGROUND: "배경을 설명한 기사",
};

interface DocumentItemProps {
  title: string | null;
  publisher: string | null;
  url: string | null;
  publishedAt: string | null;
  /** 관련 설명 줄(관계 문구, 연결 사건 등) */
  relation?: ReactNode;
  quotes?: DocumentQuoteItem[];
  headingLevel?: "h3" | "h4";
  className?: string;
  sentiment?: SentimentJudgement | null;
  sentimentName?: string;
}

export function DocumentItem({ title, publisher, url, publishedAt, relation, quotes = [], headingLevel: Heading = "h3", className, sentiment, sentimentName }: DocumentItemProps) {
  return (
    <article className={cn("flex flex-col gap-2", className)}>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-secondary">
        <span className="font-medium text-text-primary">{publisher ?? "출처 미상"}</span>
        <span aria-hidden="true">·</span>
        <span>
          발행{" "}
          <time className="tabular-nums" dateTime={publishedAt ?? undefined}>
            {formatKst(publishedAt)}
          </time>
        </span>
      </p>
      <Heading className="text-base leading-snug font-medium text-text-primary">{title ?? "제목 없는 문서"}</Heading>
      <SentimentLabel judgement={sentiment} accessibleName={sentimentName ?? title ?? "문서"} />
      {relation && <div className="text-sm text-text-secondary">{relation}</div>}
      {quotes.map((q) => (
        <div key={q.id} className="flex items-start gap-2">
          <blockquote className="min-w-0 flex-1 bg-surface-sunken px-4 py-3 text-base leading-relaxed text-text-primary">“{q.quote}”</blockquote>
          <span className="pt-3">
            <VerificationBadge verified={q.quoteVerified} />
          </span>
        </div>
      ))}
      {url ? (
        <a
          href={url}
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
    </article>
  );
}
