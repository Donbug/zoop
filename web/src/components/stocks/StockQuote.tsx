import { useCallback, type ReactNode } from 'react';
import { getCompanyQuote } from '@/apis/companies/companies';
import { useAsyncData } from '@/hooks/useAsyncData';
import { formatMoney } from '@/util/format';

/** 등락률(비율)을 화살표와 부호가 붙은 백분율로. 오르면 빨강, 내리면 파랑(국내 관례) */
function ChangeRate({ rate }: { rate: number }) {
  const percent = Math.abs(rate * 100).toFixed(2);
  if (rate > 0)
    return (
      <span className="mt-0.5 text-[10px] text-zoop-up">▲ +{percent}%</span>
    );
  if (rate < 0)
    return (
      <span className="mt-0.5 text-[10px] text-zoop-down">▼ -{percent}%</span>
    );
  return <span className="mt-0.5 text-[10px] text-zoop-muted">0.00%</span>;
}

function Frame({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <span
      aria-label={label}
      className="flex min-w-[84px] flex-col items-end font-inter max-md:min-w-0"
    >
      {children}
    </span>
  );
}

const muted = 'text-[10px] text-zoop-muted';

// 종목 행의 최신 시세. 행마다 따로 조회하며, 시세가 없거나 실패해도 행은 그대로 쓸 수 있다.
export default function StockQuote({ companyId }: { companyId: string }) {
  const load = useCallback(() => getCompanyQuote(companyId), [companyId]);
  const quote = useAsyncData(load);

  if (quote.status === 'loading') {
    return (
      <Frame label="시세 불러오는 중">
        <span className={muted}>…</span>
      </Frame>
    );
  }
  if (quote.status === 'error') {
    return (
      <Frame>
        <span className={muted}>시세 확인 실패</span>
      </Frame>
    );
  }
  if (quote.data.status === 'unavailable') {
    return (
      <Frame>
        <span className={muted}>시세 없음</span>
      </Frame>
    );
  }
  const { price, currency, changeRate } = quote.data.quote;
  return (
    <Frame>
      <strong className="text-[13px] font-bold text-zoop-ink tabular-nums">
        {formatMoney(price, currency)}
      </strong>
      {changeRate !== null && <ChangeRate rate={changeRate} />}
    </Frame>
  );
}
