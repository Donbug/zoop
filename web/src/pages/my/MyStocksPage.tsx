import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import PageShell from '@/components/common/PageShell';
import HoldingsSection from '@/components/my/HoldingsSection';
import WatchlistSection from '@/components/my/WatchlistSection';
import PortfolioConnect from '@/components/portfolio/PortfolioConnect';
import { getPortfolio } from '@/apis/portfolio/portfolio';
import { getSettings } from '@/apis/settings/settings';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useAuth } from '@/hooks/useAuth';
import type { CompanySearchTerms } from '@/types/company';

const CONNECT_PARAM = 'account';
const CONNECT_VALUE = 'connect';

// D-MY-01 / 01b 내 종목
// - 보유(가상 계좌)와 관심 종목은 서로 독립된 상태다(연결됨/안 됨 × 관심 있음/0개).
// - [가상 계좌 연결하기]는 /my?account=connect로 같은 화면 안에서 공용 연결 기능을 연다.
//   목록은 숨기기만 하고 언마운트하지 않아 관심 검색어·결과가 남고, 돌아오면 스크롤 위치를 되살린다.
//   연결 성공·취소·브라우저 뒤로 가기 모두 내 종목으로 돌아온다.
export default function MyStocksPage() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const connecting = params.get(CONNECT_PARAM) === CONNECT_VALUE;
  const settings = useAsyncData(getSettings);
  const portfolio = useAsyncData(getPortfolio);
  const { reload: reloadPortfolio } = portfolio;
  const [terms, setTerms] = useState<CompanySearchTerms>({
    draft: '',
    query: '',
  });
  const [logoutPending, setLogoutPending] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
  const savedScroll = useRef<number | null>(null);
  const wasConnecting = useRef(connecting);

  useEffect(() => {
    if (connecting) {
      window.scrollTo(0, 0);
    } else if (savedScroll.current !== null) {
      window.scrollTo(0, savedScroll.current);
      savedScroll.current = null;
    }
    // 연결 화면에서 돌아오면(성공·취소·뒤로 가기·연결 화면에서 확인한 기존 연결) 보유를 다시 읽는다.
    if (wasConnecting.current && !connecting) reloadPortfolio();
    wasConnecting.current = connecting;
  }, [connecting, reloadPortfolio]);

  const openConnect = () => {
    savedScroll.current = window.scrollY;
    navigate(`/my?${CONNECT_PARAM}=${CONNECT_VALUE}`, {
      state: { from: 'my' },
    });
  };

  // 내 종목에서 열었으면 기록을 하나 되돌려 앞으로 가기에 연결 화면이 남지 않게 한다.
  const closeConnect = () => {
    if ((location.state as { from?: string } | null)?.from === 'my') {
      navigate(-1);
    } else {
      navigate('/my', { replace: true });
    }
  };

  const handleLogout = async () => {
    if (logoutPending) return;
    setLogoutPending(true);
    setLogoutError(false);
    try {
      if (await logout()) navigate('/login', { replace: true });
    } catch {
      setLogoutError(true);
    } finally {
      setLogoutPending(false);
    }
  };

  return (
    <>
      {connecting && (
        <div className="mx-auto max-w-xl py-8">
          <PortfolioConnect
            source="my"
            onBack={closeConnect}
            onConnected={closeConnect}
          />
        </div>
      )}
      <div hidden={connecting}>
        <PageShell title="내 종목">
          <HoldingsSection portfolio={portfolio} onConnect={openConnect} />
          <WatchlistSection
            settings={settings}
            portfolio={portfolio}
            terms={terms}
            onTermsChange={setTerms}
          />
          {logoutError && (
            <p role="alert">로그아웃하지 못했어요. 다시 시도해 주세요.</p>
          )}
          <button
            type="button"
            onClick={() => void handleLogout()}
            className="underline"
            disabled={logoutPending}
            aria-busy={logoutPending}
          >
            {logoutPending
              ? '로그아웃 중…'
              : logoutError
                ? '로그아웃 다시 시도'
                : '로그아웃'}
          </button>
        </PageShell>
      </div>
    </>
  );
}
