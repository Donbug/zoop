// 브리핑의 주요 시장 지표(FS031): KOSPI·KOSDAQ·원/달러. 값은 회차를 만들 때 받아 저장한 것이라 발행 뒤에도 바뀌지 않는다.
//  - 지표마다 독립: 하나가 불러오지 못했거나 아직 없어도 나머지는 그대로 보인다.
//  - 상태는 글자로 구분한다: 지연(값은 보이되 지연 표지), 불러오지 못했어요(요청 실패), 아직 없어요(출처에 그 시점 값이 없음).
//  - 변화는 관측한 값끼리의 차이만 적는다. 영향 해석·전망은 두지 않는다.
import { ChartLine, CircleAlert, Clock, ExternalLink, Info } from "lucide-react";
import { useId } from "react";
import type { Schemas } from "@/api/client";
import { PriceChange } from "@/components/domain/status-labels";
import { Badge } from "@/components/ui/badge";
import { IconHint } from "@/components/ui/icon-hint";
import { baselineBasis, formatIndicatorValue, observedBasis, type Indicator } from "@/lib/briefing-market";
import { formatKst } from "@/lib/labels";

type Market = Schemas["BriefingResponse"]["marketVariables"];

function IndicatorItem({ indicator }: { indicator: Indicator }) {
  const value = indicator.value;
  const lines = [observedBasis(indicator), baselineBasis(indicator)].filter(Boolean);
  return (
    <li className="flex items-start justify-between gap-3 py-3 md:flex-col md:items-stretch md:px-4 md:first:pl-0 md:last:pr-0">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-base font-semibold text-text-primary">{indicator.label}</span>
          {indicator.status === "delayed" && (
            <Badge variant="warning">
              <Clock aria-hidden="true" />
              지연
            </Badge>
          )}
        </div>
        {value !== null && (
          <p className="flex flex-col text-sm text-text-secondary tabular-nums">
            {lines.map((line) => (
              <span key={line}>{line}</span>
            ))}
            {indicator.status === "delayed" && indicator.reason && <span>{indicator.reason}</span>}
          </p>
        )}
      </div>
      {value !== null ? (
        <div className="flex shrink-0 flex-col items-end gap-0.5 md:items-start">
          <data value={value} className="text-xl font-semibold text-text-primary tabular-nums">
            {formatIndicatorValue(value, indicator.unit)}
          </data>
          <PriceChange
            change={indicator.change}
            changePercent={indicator.changeRate === null ? null : indicator.changeRate * 100}
            formatAmount={(amount) => formatIndicatorValue(amount, indicator.unit)}
            className="text-sm"
          />
        </div>
      ) : (
        <div className="flex min-w-0 flex-col items-end gap-0.5 text-right md:items-start md:text-left">
          <p className="flex items-center gap-1.5 text-base font-medium text-text-primary">
            {indicator.status === "failed" ? <CircleAlert className="size-4 shrink-0 text-error" aria-hidden="true" /> : <Clock className="size-4 shrink-0 text-text-secondary" aria-hidden="true" />}
            {indicator.status === "failed" ? "불러오지 못했어요" : "아직 없어요"}
          </p>
          {indicator.reason && <p className="text-sm text-text-secondary">{indicator.reason}</p>}
        </div>
      )}
    </li>
  );
}

export function MarketIndicatorsSection({ market }: { market: Market }) {
  const titleId = useId();
  const heading = (
    <h3 id={titleId} className="flex items-center gap-2 text-base font-semibold text-text-primary">
      <ChartLine className="size-5 text-text-secondary" aria-hidden="true" />
      주요 시장 지표
    </h3>
  );
  if (market.status === "unavailable") {
    return (
      <section aria-labelledby={titleId} className="flex flex-col gap-2 pt-4 pb-3">
        {heading}
        <p className="flex items-center gap-2 text-sm text-text-secondary">
          <Info className="size-4 shrink-0" aria-hidden="true" />
          {market.reason}
        </p>
      </section>
    );
  }
  const source = market.indicators.find((i) => i.source)?.source;
  return (
    <section aria-labelledby={titleId} className="pt-4">
      <div className="flex items-center justify-between gap-2">
        {heading}
        <IconHint icon={Info} label="시장 지표 안내">
          <p>이 회차를 만들 때 받은 값이고, 발행한 뒤에는 바뀌지 않아요.</p>
          {source && (
            <p>
              출처 {source.name}. {source.delayNote}
            </p>
          )}
          <p>값을 받은 시각 {formatKst(market.collectedAt)}</p>
          <ul className="mt-1 flex flex-col">
            {market.indicators
              .filter((i) => i.source?.url)
              .map((i) => (
                <li key={i.id}>
                  <a
                    href={i.source?.url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex min-h-8 items-center gap-1 text-text-primary underline underline-offset-2"
                    aria-label={`${i.label} 출처 열기`}
                  >
                    {i.label}
                    <ExternalLink className="size-3.5" aria-hidden="true" />
                  </a>
                </li>
              ))}
          </ul>
        </IconHint>
      </div>
      <ul className="mt-1 grid divide-y divide-border-subtle md:grid-cols-3 md:divide-x md:divide-y-0">
        {market.indicators.map((indicator) => (
          <IndicatorItem key={indicator.id} indicator={indicator} />
        ))}
      </ul>
    </section>
  );
}
