import { Link, useLocation } from 'react-router-dom';
import CompanyLogo from '@/components/common/CompanyLogo';
import StockQuote from '@/components/stocks/StockQuote';
import { getPortfolio } from '@/apis/portfolio/portfolio';
import { useAsyncData } from '@/hooks/useAsyncData';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';

// D-GRP-01/01b 지도 왼쪽 내 종목 사이드바: 가상 계좌의 보유 종목을 보이고, 누르면 지도에서
// 그 기업으로 이동한다. 시세는 종목마다 따로 조회한다(StockQuote).
export default function HoldingsSidebar({
  member,
  logoOf,
  onPick,
  onClose,
}: {
  /** 회원일 때만 보유 종목을 조회한다. */
  member: boolean;
  logoOf: (companyId: string) => string | null | undefined;
  onPick: (companyId: string) => void;
  onClose: () => void;
}) {
  const location = useLocation();
  return (
    <aside
      aria-labelledby="holdings-sidebar-title"
      className="flex w-[280px] shrink-0 flex-col overflow-hidden rounded-[6px] border-[0.667px] border-zoop-line bg-zoop-paper max-md:w-full"
    >
      <header className="flex items-center justify-between border-b-[0.667px] border-zoop-line px-4 py-3">
        <h2
          id="holdings-sidebar-title"
          className="m-0 text-[15px] font-bold text-zoop-ink"
        >
          내가 보유 중인 종목
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="보유 종목 사이드바 닫기"
          className="grid size-7 place-items-center rounded text-zoop-muted hover:bg-zoop-soft focus-visible:outline-2"
        >
          ×
        </button>
      </header>
      {member ? (
        <HoldingsList logoOf={logoOf} onPick={onPick} />
      ) : (
        <p className={`${ui.muted} px-4 py-4`}>
          로그인하면 가상 계좌의 보유 종목을 볼 수 있어요.{' '}
          <Link
            to="/login"
            state={{ from: location }}
            className="font-semibold underline"
          >
            로그인
          </Link>
        </p>
      )}
    </aside>
  );
}

function HoldingsList({
  logoOf,
  onPick,
}: {
  logoOf: (companyId: string) => string | null | undefined;
  onPick: (companyId: string) => void;
}) {
  const portfolio = useAsyncData(getPortfolio);
  if (portfolio.status === 'loading')
    return (
      <p role="status" className="px-4 py-4 text-[12px] text-zoop-muted">
        보유 종목을 불러오는 중이에요.
      </p>
    );
  if (portfolio.status === 'error')
    return (
      <div role="alert" className="px-4 py-4 text-[12px] text-zoop-muted">
        보유 종목을 불러오지 못했어요.{' '}
        <button
          type="button"
          onClick={portfolio.reload}
          className="font-semibold underline"
        >
          다시 시도
        </button>
      </div>
    );
  const holdings = portfolio.data.holdings;
  if (!holdings.length)
    return (
      <p className="px-4 py-4 text-[12px] text-zoop-muted">
        보유 종목이 없어요.{' '}
        <Link to="/my" className="font-semibold underline">
          가상 계좌 연결하기
        </Link>
      </p>
    );
  return (
    <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-0">
      {holdings.map((holding) => (
        <li key={holding.companyId}>
          <button
            type="button"
            onClick={() => onPick(holding.companyId)}
            aria-label={`${holding.name}, 지도에서 보기`}
            className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-zoop-soft focus-visible:outline-2"
          >
            <CompanyLogo
              name={holding.name}
              logoUrl={logoOf(holding.companyId)}
              className="size-9 rounded-full border-[0.667px] border-zoop-line bg-zoop-paper text-sm font-bold text-zoop-ink"
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold text-zoop-ink">
                {holding.name}
              </span>
              <span className="block text-[11px] text-zoop-faint">
                {holding.quantity.toLocaleString('ko-KR')}주
              </span>
            </span>
            <StockQuote companyId={holding.companyId} />
          </button>
        </li>
      ))}
    </ul>
  );
}
