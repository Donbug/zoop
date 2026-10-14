import { useCallback } from 'react';
import { getCompanyQuote } from '@/apis/companies/companies';
import { useAsyncData } from '@/hooks/useAsyncData';
import { formatMoney } from '@/util/format';

/** 등락률(비율)을 화살표와 부호가 붙은 백분율로. 오르면 빨강, 내리면 파랑(국내 관례) */
function ChangeRate({ rate }: { rate: number }) {
  const percent = Math.abs(rate * 100).toFixed(2);
  if (rate > 0) return <span className="is-up">▲ +{percent}%</span>;
  if (rate < 0) return <span className="is-down">▼ -{percent}%</span>;
  return <span className="is-flat">0.00%</span>;
}

// 종목 행의 최신 시세. 행마다 따로 조회하며, 시세가 없거나 실패해도 행은 그대로 쓸 수 있다.
export default function StockQuote({ companyId }: { companyId: string }) {
  const load = useCallback(() => getCompanyQuote(companyId), [companyId]);
  const quote = useAsyncData(load);

  if (quote.status === 'loading') {
    return (
      <span className="stocks-quote" aria-label="시세 불러오는 중">
        <span className="is-empty">…</span>
      </span>
    );
  }
  if (quote.status === 'error') {
    return (
      <span className="stocks-quote">
        <span className="is-empty">시세 확인 실패</span>
      </span>
    );
  }
  if (quote.data.status === 'unavailable') {
    return (
      <span className="stocks-quote">
        <span className="is-empty">시세 없음</span>
      </span>
    );
  }
  const { price, currency, changeRate } = quote.data.quote;
  return (
    <span className="stocks-quote">
      <strong>{formatMoney(price, currency)}</strong>
      {changeRate !== null && <ChangeRate rate={changeRate} />}
    </span>
  );
}
