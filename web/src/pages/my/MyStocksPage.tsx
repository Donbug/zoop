import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import PageShell from '@/components/common/PageShell';
import HoldingsSection from '@/components/my/HoldingsSection';
import WatchlistSection from '@/components/my/WatchlistSection';
import PortfolioConnect from '@/components/portfolio/PortfolioConnect';
import { getPortfolio } from '@/apis/portfolio/portfolio';
import { getSettings } from '@/apis/settings/settings';
import { useAsyncData } from '@/hooks/useAsyncData';
import type { CompanySearchTerms } from '@/types/company';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';

const CONNECT_PARAM = 'account';
const CONNECT_VALUE = 'connect';

// D-MY-01 / 01b 내 종목
// - 보유(가상 계좌)와 관심 종목은 서로 독립된 상태다(연결됨/안 됨 × 관심 있음/0개).
// - [가상 계좌 연결하기]는 /my?account=connect로 같은 화면 안에서 공용 연결 기능을 연다.
//   목록은 숨기기만 하고 언마운트하지 않아 관심 검색어·결과가 남고, 돌아오면 스크롤 위치를 되살린다.
//   연결 성공·취소·브라우저 뒤로 가기 모두 내 종목으로 돌아온다.
export default function MyStocksPage() {
  const ownerId = useAuthStore(selectMemberId);
  return <MyStocksWorkspace key={ownerId ?? 'anonymous'} ownerId={ownerId} />;
}

// FS054: 회원별 조회·검색·계좌 작업을 분리하고 같은 회원의 세션 갱신에는 유지한다.
function MyStocksWorkspace({ ownerId }: { ownerId: string | null }) {
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
  const savedScroll = useRef<number | null>(null);
  const wasConnecting = useRef(connecting);
  const active = useRef(true);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

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
    // 이전 회원의 연결 응답이나 화면을 떠난 뒤의 응답은 현재 경로를 바꾸지 않는다.
    // 연결 화면 인스턴스의 수명은 ConnectScreen이 따로 확인한다.
    if (!active.current || selectMemberId(useAuthStore.getState()) !== ownerId)
      return;
    if ((location.state as { from?: string } | null)?.from === 'my') {
      navigate(-1);
    } else {
      navigate('/my', { replace: true });
    }
  };

  return (
    <>
      {connecting && <ConnectScreen onClose={closeConnect} />}
      <div hidden={connecting}>
        <PageShell title="내 종목">
          <HoldingsSection portfolio={portfolio} onConnect={openConnect} />
          <WatchlistSection
            settings={settings}
            portfolio={portfolio}
            terms={terms}
            onTermsChange={setTerms}
          />
        </PageShell>
      </div>
    </>
  );
}

// 연결 화면 한 번 열림의 수명. 뒤로 가기로 닫힌 뒤 도착한 늦은 연결 성공은 내 종목 화면이 살아 있어도
// 경로를 다시 바꾸지 않는다(다시 연 연결 화면은 새 인스턴스라 따로 동작한다).
function ConnectScreen({ onClose }: { onClose: () => void }) {
  const open = useRef(true);
  useEffect(() => {
    open.current = true;
    return () => {
      open.current = false;
    };
  }, []);
  const close = () => {
    if (open.current) onClose();
  };
  return (
    <div className="mx-auto max-w-xl py-8">
      <PortfolioConnect source="my" onBack={close} onConnected={close} />
    </div>
  );
}
