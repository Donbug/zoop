// 지도 기업 패널의 요약. 기업 상세와 같은 조회 훅·키를 사용하고 각 영역은 독립적으로 실패한다.
import { Newspaper, Star, Wallet } from "lucide-react";
import { ApiError, type Schemas } from "@/api/client";
import { useAsOfRound, useCompany, useCompanyDocuments, useCompanyPrices } from "@/api/queries";
import { CompanyQuote } from "@/features/company-quote";
import { CompanyMetrics } from "@/features/company-metrics";
import { CompanyHolding } from "@/features/company-holding";
import { ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { SectionHeader } from "@/components/ui/section-header";
import { formatKst } from "@/lib/labels";
import type { DetailRange } from "@/lib/company-timeline";
import { formatPrice, toneOf } from "@/lib/market";
import { CompanyMark } from "./company-mark";
import { DocumentItem } from "./document-item";
import { SentimentLabel } from "./status-labels";

export function CompanyPanelSummary({ companyId, range }: { companyId: string; range: DetailRange }) {
  const round = useAsOfRound();
  const company = useCompany(companyId, round ? null : range.to);
  return (
    <div className="flex flex-col gap-3 px-4 [&_dl]:grid-cols-2 [&_dl]:md:grid-cols-2">
      {company.isPending ? <SkeletonRows count={1} label="기업 기본 정보를 불러오고 있어요" /> : company.data && (
        <section aria-label="기업 기본 정보" className="flex items-start gap-3">
          <CompanyMark id={companyId} name={company.data.name} brandColor={company.data.brandColor} logoUrl={company.data.logoUrl} size={40} />
          <div className="flex min-w-0 flex-col gap-1 text-base text-text-secondary">
            <p className="tabular-nums">{[company.data.ticker, company.data.sector].filter(Boolean).join(" · ")}</p>
            {(company.data.holding || company.data.watch) && <p className="flex gap-2 text-sm">{company.data.holding && <span className="inline-flex items-center gap-1"><Wallet className="size-4" aria-hidden="true" />보유 종목</span>}{company.data.watch && <span className="inline-flex items-center gap-1"><Star className="size-4" aria-hidden="true" />관심 종목</span>}</p>}
            {company.data.aliases.length > 0 && <details><summary className="min-h-11 cursor-pointer py-3 text-sm">기업명 더 보기</summary><p className="text-sm">{company.data.aliases.join(" · ")}</p></details>}
          </div>
        </section>
      )}
      <CompanyQuote companyId={companyId} />
      <CompanyPanelPriceChart companyId={companyId} range={range} />
      <details className="border-y border-border-subtle py-1">
        <summary className="min-h-11 cursor-pointer py-3 text-base font-semibold text-text-primary">주요 지표</summary>
        <div className="pb-3"><CompanyMetrics companyId={companyId} /></div>
      </details>
      <CompanyHolding companyId={companyId} />
    </div>
  );
}

function CompanyPanelPriceChart({ companyId, range }: { companyId: string; range: DetailRange }) {
  const prices = useCompanyPrices(companyId, range);
  if (prices.isPending) return <SkeletonRows count={1} label="시세 추이를 불러오고 있어요" />;
  if (prices.isError) return <ErrorState compact title="시세 추이를 불러오지 못했어요" error={prices.error} onRetry={() => void prices.refetch()} />;
  const data = prices.data;
  if (data.status === "unavailable" && data.reasonCode === "temporary_failure") return <ErrorState compact title="시세 추이를 불러오지 못했어요" error={new ApiError(200, data.reasonCode, data.reason)} onRetry={() => void prices.refetch()} />;
  if (data.status !== "available" || data.points.length === 0) return null;
  const values = data.points.map((p) => p.close);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const first = data.points[0]!;
  const last = data.points.at(-1)!;
  const width = 320;
  const height = 72;
  const line = values.map((v, i) => `${i === 0 ? "M" : "L"}${values.length === 1 ? width / 2 : i * width / (values.length - 1)},${high === low ? height / 2 : 4 + (high - v) / (high - low) * (height - 8)}`).join(" ");
  const tone = toneOf(last.close - first.close);
  const stroke: Record<typeof tone, string> = { up: "stroke-up", down: "stroke-down", flat: "stroke-text-secondary" };
  return (
    <figure aria-label={`최근 1개월 시세 추이. 처음 ${formatPrice(first.close, data.currency)}, 마지막 ${formatPrice(last.close, data.currency)}. 최저 ${formatPrice(low, data.currency)}, 최고 ${formatPrice(high, data.currency)}.`} className="flex flex-col gap-1">
      <figcaption className="text-sm text-text-secondary">최근 1개월 시세 추이</figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="거래 시각별 종가 추이" className="h-20 w-full overflow-visible"><path d={line} fill="none" strokeWidth={2} className={stroke[tone]} vectorEffect="non-scaling-stroke" /></svg>
      <p className="flex justify-between text-sm text-text-secondary tabular-nums"><span>{formatKst(first.time)}</span><span>{formatKst(last.time)}</span></p>
      <p className="text-sm text-text-secondary">{data.source.name} · 마지막 거래 {formatKst(last.time)}</p>
    </figure>
  );
}

export function CompanyPanelNews({ companyId, range }: { companyId: string; range: DetailRange }) {
  const round = useAsOfRound();
  const documents = useCompanyDocuments(companyId, round ? undefined : range);
  return (
    <section aria-label="뉴스·공시">
      <SectionHeader as="h3" icon={Newspaper} title="뉴스·공시" />
      <div className="px-4">
        {documents.isPending ? <SkeletonRows count={2} label="뉴스·공시를 불러오고 있어요" /> : documents.isError ? <ErrorState compact title="뉴스·공시를 불러오지 못했어요" error={documents.error} onRetry={() => void documents.refetch()} /> : documents.data.items.length === 0 ? <p className="text-base text-text-secondary">이 기업 사건의 근거 문서가 없어요.</p> : <ol className="divide-y divide-border-subtle">{documents.data.items.slice(0, 3).map((doc) => (
          <li key={doc.id} className="py-3">
            <DocumentItem title={doc.title} publisher={doc.publisher} url={doc.url} publishedAt={doc.publishedAt} headingLevel="h4" sentiment={doc.sentiment} sentimentName={doc.title ?? "기업 문서"} />
          </li>
        ))}</ol>}
        {documents.data && documents.data.items.length > 3 && <p className="text-sm text-text-secondary">전체 {documents.data.items.length}건은 기업 상세의 문서에서 볼 수 있어요.</p>}
      </div>
    </section>
  );
}

/** 사건 자체의 판정을 만들지 않는다. 이 사건을 뒷받침한 기업 맥락의 문서 판정을 문서별로 표시한다. */
export function CompanyIssueSentiments({ issueId, documents }: { issueId: string; documents: Schemas["CompanyDocument"][] }) {
  return <>{documents.filter((doc) => doc.sentiment && doc.events.some((event) => event.eventId === issueId)).map((doc) => <SentimentLabel key={doc.id} judgement={doc.sentiment} accessibleName={doc.title ?? "사건 근거 문서"} />)}</>;
}
