// 기업 상세의 가상 보유 영역(FS039·FS054). 가상 계좌를 연결한 회원이 이 기업을 모의로 보유할 때만 그린다.
// 비회원·미연결·미보유·관심 종목만인 경우는 영역 자체를 그리지 않는다(0주로 바꾸지 않는다). 계좌 조회가 실패하면 미보유로 보지 않고
// 이 영역만 오류와 [다시 시도]를 보인다.
// 값은 BFF 계산 그대로다: 평가 금액 = 모의 수량 × 계산 기준 시점의 시세(시세 통화), 자산 비중 = 평가 금액 ÷ 현금을 뺀 주식 평가 금액 합계.
// 시세가 없으면 평가 금액은 '미제공', 비중을 계산할 수 없으면 '계산 불가'로 적고 0으로 채우지 않는다. 통화는 환산하지 않는다.
// 평가 손익은 평균 매입가 통화가 시세 통화와 같을 때만 보인다. 모의 정보 기준 시점과 계산 기준 시점을 나눠 적는다.
import { Info, Wallet } from "lucide-react";
import { usePortfolio, useSession } from "@/api/queries";
import { PriceChange } from "@/components/domain/status-labels";
import { ErrorState } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";
import { formatWeight } from "@/lib/holding";
import { formatKst } from "@/lib/labels";
import { formatPrice } from "@/lib/market";

const numberFormat = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });

export function CompanyHolding({ companyId }: { companyId: string }) {
  const session = useSession();
  const isMember = session.data?.kind === "member";
  const portfolio = usePortfolio(isMember);

  if (!isMember) return null;
  if (portfolio.isError)
    return <ErrorState compact error={portfolio.error} title="가상 계좌 보유를 확인하지 못했어요" onRetry={() => void portfolio.refetch()} />;
  const data = portfolio.data;
  const holding = data?.connected ? data.holdings.find((h) => h.companyId === companyId) : undefined;
  if (!data || !holding || !data.valuation) return null;

  const { valuation } = data;
  const quote = holding.quote.status === "available" ? holding.quote : null;
  const profit = quote && holding.avgPriceCurrency === quote.currency ? (quote.price - holding.avgPrice) * holding.quantity : null;

  const stats: { label: string; value: React.ReactNode }[] = [
    { label: "보유 수량", value: `${numberFormat.format(holding.quantity)}주` },
    {
      label: "평균 매입가",
      value: holding.avgPriceCurrency ? formatPrice(holding.avgPrice, holding.avgPriceCurrency) : numberFormat.format(holding.avgPrice),
    },
    {
      label: "평가 금액",
      value: quote && holding.marketValue !== null ? formatPrice(holding.marketValue, quote.currency) : <span className="text-text-secondary">미제공</span>,
    },
    {
      label: "자산 비중",
      value: holding.weight === null ? <span className="text-text-secondary">{formatWeight(null)}</span> : formatWeight(holding.weight),
    },
  ];
  if (quote && profit !== null)
    stats.push({
      label: "평가 손익",
      value: (
        <PriceChange
          change={profit}
          changePercent={holding.avgPrice ? (profit / (holding.avgPrice * holding.quantity)) * 100 : null}
          currency={quote.currency}
          className="text-lg"
        />
      ),
    });

  return (
    <section aria-labelledby="company-holding-title" className="flex flex-col gap-2 border-y border-border-subtle py-3">
      <div className="flex items-center gap-2">
        <h2 id="company-holding-title" className="flex items-center gap-2 text-base font-semibold text-text-primary">
          <Wallet className="size-5 text-text-secondary" aria-hidden="true" />
          가상 계좌 보유
        </h2>
        <IconHint icon={Info} label="평가 기준">
          <p>연결한 가상 계좌의 모의 데이터예요. 실제 계좌가 아니에요.</p>
          {quote ? (
            <p>
              평가 금액은 보유 수량 × 현재가예요({quote.sourceName}, 시세 기준 {formatKst(quote.asOf)}).
            </p>
          ) : (
            <p>주가를 받지 못해 평가 금액을 계산하지 않았어요. {holding.quote.status === "unavailable" && holding.quote.reason}</p>
          )}
          <p>자산 비중은 현금을 뺀 보유 주식 평가 금액 합계에서 이 종목이 차지하는 몫이에요.</p>
          {quote && profit === null && <p>평균 매입가의 통화가 시세 통화와 같지 않거나 알 수 없어 평가 손익은 보여 드리지 않아요.</p>}
        </IconHint>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 md:grid-cols-5">
        {stats.map((s) => (
          <div key={s.label} className="flex min-w-0 flex-col gap-0.5">
            <dt className="text-sm text-text-secondary">{s.label}</dt>
            <dd className="text-lg font-semibold text-text-primary tabular-nums">{s.value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col gap-0.5 text-sm text-text-secondary tabular-nums">
        <p>
          모의 정보 기준 {formatKst(data.mockAsOf)} · 평가 계산 {formatKst(valuation.calculatedAt)}
        </p>
        {valuation.weightUnavailableReason && <p>자산 비중: {valuation.weightUnavailableReason}</p>}
      </div>
    </section>
  );
}
