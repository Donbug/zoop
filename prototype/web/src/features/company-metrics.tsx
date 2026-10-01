// 기업 상세 주요 지표(요구 39 중 출처가 주는 범위). 시세와 다른 출처(네이버 증권)라 따로 조회하고 출처·기준을 따로 적는다.
//  - 값은 출처가 적은 그대로(1,609조 1,882억 · 12.35배 · 0.61%), 지표마다 출처의 기준 기간(2026.06.)을 붙인다. 계산·추정·환산하지 않는다.
//  - 토스증권 시세에 시가총액(현재가 × 발행주식수)이 있으면 그 값을 쓰고, 이 영역의 시가총액은 숨긴다.
//  - 일시 장애는 이 영역만 [다시 시도], 미지원·형식 변경 등은 사유 한 줄. 시세 영역은 그대로다(요구 54).
import { ApiError } from "@/api/client";
import { useCompanyMetrics, useCompanyQuote } from "@/api/queries";
import { ErrorState, LoadingBlock, Skeleton } from "@/components/ui/feedback";
import { formatKst } from "@/lib/labels";
import { QuoteSourceHint, UnavailableLine } from "./company-quote";

export function CompanyMetrics({ companyId }: { companyId: string }) {
  const metrics = useCompanyMetrics(companyId);
  const quote = useCompanyQuote(companyId);
  const tossMarketCap = quote.data?.status === "available" && quote.data.source.provider === "toss" && quote.data.quote.marketCap != null;

  let body;
  if (metrics.isPending) {
    body = (
      <LoadingBlock label="주요 지표를 불러오고 있어요" className="flex flex-col gap-2">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-10 w-full" />
      </LoadingBlock>
    );
  } else if (metrics.isError) {
    body = <ErrorState compact error={metrics.error} title="주요 지표를 불러오지 못했어요" onRetry={() => void metrics.refetch()} />;
  } else if (metrics.data.status === "unavailable") {
    const data = metrics.data;
    body =
      data.reasonCode === "temporary_failure" ? (
        <ErrorState compact title="주요 지표를 불러오지 못했어요" error={new ApiError(200, data.reasonCode, data.reason)} message={data.reason} onRetry={() => void metrics.refetch()} />
      ) : (
        <UnavailableLine>{data.reason}</UnavailableLine>
      );
  } else {
    const { source, asOf } = metrics.data;
    const items = metrics.data.items.filter((m) => !(tossMarketCap && m.code === "marketValue"));
    if (items.length === 0) return null;
    body = (
      <>
        <div className="flex flex-wrap items-center gap-x-1 text-sm text-text-secondary">
          <span className="tabular-nums">
            주요 지표 · {source.name} · 기준 {formatKst(asOf)}
          </span>
          <QuoteSourceHint source={source} asOf={asOf} />
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 md:grid-cols-4">
          {items.map((m) => (
            <div key={m.code} className="flex min-w-0 flex-col gap-0.5">
              <dt className="text-sm text-text-secondary">{m.label}</dt>
              <dd className="flex flex-wrap items-baseline gap-x-1 text-base font-semibold text-text-primary tabular-nums">
                {m.value}
                {m.basis && <span className="text-sm font-normal text-text-secondary">({m.basis} 기준)</span>}
              </dd>
            </div>
          ))}
        </dl>
      </>
    );
  }

  return (
    <section aria-labelledby="company-metrics-title" className="flex flex-col gap-1">
      <h2 id="company-metrics-title" className="sr-only">
        주요 지표
      </h2>
      {body}
    </section>
  );
}
