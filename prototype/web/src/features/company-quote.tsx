// 기업 상세 시세 영역(요구 35·72). 기업 개요와 따로 조회해 늦거나 실패해도 다른 영역을 막지 않는다(요구 54).
//  - 현재가·전일 대비(색 + 부호 + 화살표 + 글자)·기준 시각·출처, 받은 지표만(시가총액·거래량·당일 고저·52주 고저).
//  - 출처 상세(공식 여부·지연 가능·BFF가 계산한 값·출처 링크)는 Info 팝오버에 둔다.
//  - 출처 장애는 BFF가 503 source_unavailable로 보낸다: 이 영역만 서버 사유를 보이고, 일시 장애(retryable)만 [다시 시도].
//    미연결·미지원 종목·자료 없음(200 unavailable)은 사유 한 줄. 값을 지어내지 않는다.
import { ChartNoAxesColumn, ExternalLink, Info } from "lucide-react";
import { ApiError, type Schemas } from "@/api/client";
import { useCompanyQuote } from "@/api/queries";
import { ErrorState, LoadingBlock, Skeleton } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";
import { formatKst } from "@/lib/labels";
import { PriceChange } from "@/components/domain/status-labels";
import { formatCompact, formatCompactMoney, formatPrice } from "@/lib/market";

/** 계산값 설명. 받은 값이 아니라 BFF가 출처 자료로 계산한 항목만 적는다. */
const derivedNote: Record<string, string> = {
  marketCap: "시가총액은 현재가 × 발행주식수로 계산했어요.",
  previousClose: "전일 종가는 직전 거래일 일봉 종가예요.",
  fiftyTwoWeekHigh: "52주 고저는 최근 1년 일봉으로 계산했어요.",
};

export function QuoteSourceHint({ source, asOf, derived = [] }: { source: Schemas["QuoteSourceOut"]; asOf?: string | null; derived?: string[] }) {
  return (
    <IconHint icon={Info} label={`시세 출처: ${source.name}`}>
      <p>
        {source.official ? "공식 시세 API" : "공개 자료"} · 종목 기호 {source.symbol}
      </p>
      {source.delayNote && <p>{source.delayNote}</p>}
      {asOf !== undefined && <p>기준 {formatKst(asOf)}</p>}
      {derived.map((d) => derivedNote[d]).filter(Boolean).map((note) => (
        <p key={note}>{note}</p>
      ))}
      {source.url && (
        <a href={source.url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1 font-medium text-brand-primary underline-offset-4 hover:underline">
          출처에서 확인하기
          <ExternalLink className="size-4" aria-hidden="true" />
        </a>
      )}
    </IconHint>
  );
}

export function UnavailableLine({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-sm text-text-secondary">
      <ChartNoAxesColumn className="size-4 shrink-0" aria-hidden="true" />
      {children}
    </p>
  );
}

/** 시세·지표·차트 조회 오류. 출처 장애(503 source_unavailable)는 서버가 준 사유를 쓰고, 다시 해도 같은 장애(retryable=false)에는 [다시 시도]를 두지 않는다. */
export function MarketErrorState({ error, title, onRetry }: { error: unknown; title: string; onRetry: () => void }) {
  const source = error instanceof ApiError && error.code === "source_unavailable" ? error : null;
  return <ErrorState compact error={error} title={title} message={source?.message} onRetry={source?.details?.retryable === false ? undefined : onRetry} />;
}

export function CompanyQuote({ companyId }: { companyId: string }) {
  const quote = useCompanyQuote(companyId);

  let body;
  if (quote.isPending) {
    body = (
      <LoadingBlock label="시세를 불러오고 있어요" className="flex flex-col gap-2">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-4 w-56" />
      </LoadingBlock>
    );
  } else if (quote.isError) {
    body = <MarketErrorState error={quote.error} title="시세를 불러오지 못했어요" onRetry={() => void quote.refetch()} />;
  } else if (quote.data.status === "unavailable") {
    body = <UnavailableLine>{quote.data.reason}</UnavailableLine>;
  } else {
    const { quote: q, source } = quote.data;
    const range = (low: number | null, high: number | null) =>
      low != null && high != null ? `${formatPrice(low, q.currency)} ~ ${formatPrice(high, q.currency)}` : null;
    const stats = ([
      ["시가총액", q.marketCap != null ? formatCompactMoney(q.marketCap, q.currency) : null],
      ["거래량", q.volume != null ? `${formatCompact(q.volume)}주` : null],
      ["당일 저가 ~ 고가", range(q.dayLow, q.dayHigh)],
      ["52주 저가 ~ 고가", range(q.fiftyTwoWeekLow, q.fiftyTwoWeekHigh)],
    ] satisfies [string, string | null][]).filter((s): s is [string, string] => s[1] !== null);
    body = (
      <>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <p className="text-xl font-bold text-text-primary tabular-nums">{formatPrice(q.price, q.currency)}</p>
          {q.change != null && (
            <p className="text-base">
              <span className="sr-only">전일 대비 </span>
              <PriceChange change={q.change} changePercent={q.changeRate != null ? q.changeRate * 100 : null} currency={q.currency} className="font-normal" />
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-1 text-sm text-text-secondary">
          <span className="tabular-nums">
            {q.change != null ? "전일 대비 · " : ""}기준 {formatKst(q.asOf)} · {source.name}
            {source.delayNote ? " · 지연 가능" : ""}
          </span>
          <QuoteSourceHint source={source} asOf={q.asOf} derived={q.derived} />
        </div>
        {stats.length > 0 && (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 pt-1 md:grid-cols-4">
            {stats.map(([label, value]) => (
              <div key={label} className="flex min-w-0 flex-col gap-0.5">
                <dt className="text-sm text-text-secondary">{label}</dt>
                <dd className="text-base font-semibold text-text-primary tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </>
    );
  }

  return (
    <section aria-labelledby="company-quote-title" className="flex flex-col gap-1">
      <h2 id="company-quote-title" className="sr-only">
        시세
      </h2>
      {body}
    </section>
  );
}
