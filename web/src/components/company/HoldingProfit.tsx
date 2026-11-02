import { ChangeRate } from '@/components/stocks/StockQuote';
import type { Portfolio } from '@/types/company/detail';

/** D-COM-01 D6: port of company-holding; no conversion across currencies. */
export default function HoldingProfit({
  holding,
}: {
  holding: Portfolio['holdings'][number];
}) {
  if (
    holding.quote.status !== 'available' ||
    holding.quote.price == null ||
    !Number.isFinite(holding.quote.price)
  )
    return (
      <>
        <dt className="sr-only">평가 안내</dt>
        <dd>시세가 없어 평가 손익을 계산하지 않았어요.</dd>
      </>
    );
  if (
    !holding.avgPriceCurrency ||
    holding.avgPriceCurrency !== holding.quote.currency
  )
    return (
      <>
        <dt className="sr-only">평가 안내</dt>
        <dd>
          평균 매입가의 통화가 시세 통화와 같지 않거나 알 수 없어 평가 손익은
          보여 드리지 않아요.
        </dd>
      </>
    );
  const profit = (holding.quote.price - holding.avgPrice) * holding.quantity;
  const cost = holding.avgPrice * holding.quantity;
  return (
    <>
      <dt>평가 손익</dt>
      <dd>
        <ChangeRate
          change={profit}
          rate={cost > 0 ? profit / cost : null}
          currency={holding.quote.currency}
          className="text-caption tabular-nums"
        />
        {cost <= 0 && <span> · 매입 금액이 0이라 수익률 계산 불가</span>}
      </dd>
    </>
  );
}
