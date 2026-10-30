import { useCallback, useEffect, useRef, useState } from 'react';
import ConfirmDialog from '@/components/common/ConfirmDialog';
import ErrorNotice from '@/components/common/ErrorNotice';
import StockRow from '@/components/my/StockRow';
import { disconnectPortfolio, getPortfolio } from '@/apis/portfolio/portfolio';
import { companyLogo } from '@/util/company-logo';
import {
  formatKst,
  formatMoney,
  formatQuantity,
  formatWeight,
} from '@/util/format';
import type { HoldingsSectionProps } from '@/types/my';
import type { Holding, Portfolio } from '@/types/portfolio';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';

const DISCONNECTED: Portfolio = {
  connected: false,
  connection: null,
  holdings: [],
  mockAsOf: null,
  valuation: null,
};

function holdingDescription(holding: Holding) {
  const value =
    holding.quote.status === 'available' && holding.marketValue !== null
      ? formatMoney(holding.marketValue, holding.quote.currency)
      : '미제공';
  return [
    holding.ticker,
    formatQuantity(holding.quantity),
    `평가 ${value}`,
    formatWeight(holding.weight),
  ]
    .filter(Boolean)
    .join(' · ');
}

// D-MY-01 / 01b 보유 종목(가상 계좌, 모의 데이터)
// - 연결됨: 머리글에 보유 종목 수와 [연결 끊기], 계좌 식별·예수금·기준 시각과 종목별 평가
// - 연결 안 됨: 머리글 '연결 안 됨', 점선 안내와 [가상 계좌 연결하기](이 화면 안에서 연결 기능을 연다)
// - 연결 끊기는 확인 창에서 한 번 더 고른다. 닫으면 요청하지 않는다.
//   실패하면 연결·보유 목록을 그대로 두고 창에서 다시 시도한다. 관심 목록은 영향받지 않는다.
export default function HoldingsSection({
  portfolio,
  onConnect,
}: HoldingsSectionProps) {
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [confirming, setConfirming] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectFailed, setDisconnectFailed] = useState(false);
  const data = portfolio.data;
  const connection = data?.connected ? data.connection : null;

  const closeConfirm = useCallback(() => {
    setConfirming(false);
    setDisconnectFailed(false);
  }, []);

  const disconnect = async () => {
    if (!connection || disconnecting) return;
    const ownerId = selectMemberId(useAuthStore.getState());
    const current = () =>
      active.current && selectMemberId(useAuthStore.getState()) === ownerId;
    setDisconnecting(true);
    setDisconnectFailed(false);
    try {
      await disconnectPortfolio(connection.id);
      if (!current()) return;
      portfolio.setData(DISCONNECTED);
      setConfirming(false);
    } catch {
      if (!current()) return;
      setDisconnectFailed(true);
      // 다른 탭에서 이미 끊었으면(404 등) 다시 시도해도 계속 실패하므로 연결 상태를 다시 확인한다.
      try {
        const latest = await getPortfolio();
        if (!current()) return;
        if (!latest.connected) {
          portfolio.setData(latest);
          closeConfirm();
        }
      } catch {
        // 확인도 실패하면 기존 연결·보유를 그대로 두고 다시 시도를 안내한다.
      }
    } finally {
      if (current()) setDisconnecting(false);
    }
  };

  return (
    <section
      aria-labelledby="my-holdings"
      className="rounded-xl border border-gray-200 bg-white p-5"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 id="my-holdings" className="flex-1 text-lg font-semibold">
          보유 종목(가상 계좌)
        </h2>
        {connection && (
          <>
            <span className="text-sm text-zoop-ink tabular-nums">
              {data?.holdings.length ?? 0}개
            </span>
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="rounded-lg px-2 py-1 text-sm font-medium text-zoop-ink hover:bg-gray-100"
            >
              연결 끊기
            </button>
          </>
        )}
        {data && !data.connected && (
          <span className="text-sm text-zoop-ink">연결 안 됨</span>
        )}
      </div>

      {portfolio.status === 'loading' && (
        <p role="status" className="text-sm text-zoop-ink">
          보유 종목을 불러오고 있어요
        </p>
      )}
      {portfolio.status === 'error' && (
        <ErrorNotice
          title="보유 종목을 불러오지 못했어요"
          onRetry={portfolio.reload}
        />
      )}

      {data && connection && (
        <>
          <div className="mb-2 flex flex-col gap-0.5 text-sm text-zoop-ink tabular-nums">
            <p>
              모의 계좌 {connection.accountId ?? '식별 정보 미제공'} · 예수금{' '}
              {connection.cash
                ? formatMoney(connection.cash.amount, connection.cash.currency)
                : '미제공'}{' '}
              · 모의 정보 기준 {formatKst(data.mockAsOf)} · 평가 계산{' '}
              {formatKst(data.valuation?.calculatedAt ?? null)}
            </p>
            {data.holdings.length > 0 &&
              data.valuation?.weightUnavailableReason && (
                <p>{data.valuation.weightUnavailableReason}</p>
              )}
          </div>
          {data.holdings.length === 0 ? (
            <p className="text-sm text-zoop-ink">
              이 계좌에는 보유 종목이 없어요.
            </p>
          ) : (
            <ul
              aria-label="보유 종목 목록"
              className="divide-y divide-gray-100"
            >
              {data.holdings.map((holding) => (
                <StockRow
                  key={holding.companyId}
                  id={holding.companyId}
                  name={holding.name}
                  logoUrl={companyLogo(holding.companyId)}
                  description={holdingDescription(holding)}
                  trailing={
                    holding.quote.status === 'available'
                      ? formatMoney(holding.quote.price, holding.quote.currency)
                      : undefined
                  }
                />
              ))}
            </ul>
          )}
        </>
      )}

      {data && !data.connected && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-gray-300 px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm text-zoop-ink">
              가상 계좌를 연결하면 모의 보유 종목과 평가 금액을 볼 수 있어요.
            </p>
            <p className="text-sm text-zoop-ink">
              실제 증권 계좌가 아니에요. 준비된 모의 데이터로 만든 계좌예요.
            </p>
          </div>
          <button
            type="button"
            onClick={onConnect}
            className="shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-zoop-ink hover:bg-gray-50"
          >
            가상 계좌 연결하기
          </button>
        </div>
      )}

      {confirming && connection && (
        <ConfirmDialog
          title="가상 계좌 연결을 끊을까요?"
          confirmLabel={disconnecting ? '끊고 있어요' : '연결 끊기'}
          pending={disconnecting}
          onConfirm={() => void disconnect()}
          onCancel={closeConfirm}
        >
          <p className="text-sm text-zoop-ink">
            {connection.label}의 보유 종목이 내 종목과 지도에서 빠져요. 관심
            종목은 그대로예요. 나중에 다시 연결할 수 있어요.
          </p>
          {disconnectFailed && (
            <ErrorNotice
              title="연결을 끊지 못했어요"
              message="계좌는 그대로 연결돼 있어요. [연결 끊기]를 다시 누르면 다시 시도해요."
            />
          )}
        </ConfirmDialog>
      )}
    </section>
  );
}
