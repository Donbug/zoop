// 가상 계좌(모의 데이터) 계약: docs/api/openapi.yaml
// MockPortfolioOption · ConnectionInfo · HoldingOut · PortfolioValuation · PortfolioResponse

/** 연결할 수 있는 가상 계좌. 실제 증권 계좌가 아니다. */
export type MockPortfolioOption = {
  id: string;
  label: string;
  accountId: string;
  holdingsCount: number;
};

/** 모의 예수금. 값이 없으면 필드가 null이다(0과 구분). */
export type MockCash = {
  amount: number;
  currency: string;
};

export type PortfolioConnection = {
  id: string;
  mockPortfolioId: string;
  label: string;
  connectedAt: string;
  accountId: string | null;
  cash: MockCash | null;
  status: 'connected';
};

export type HoldingQuote =
  | {
      status: 'available';
      price: number;
      currency: string;
      asOf: string | null;
      sourceName: string;
    }
  | { status: 'unavailable'; reason: string };

export type Holding = {
  companyId: string;
  name: string;
  ticker: string | null;
  quantity: number;
  avgPrice: number;
  avgPriceCurrency: string | null;
  quote: HoldingQuote;
  /** 시세가 없으면 null(0이 아님) */
  marketValue: number | null;
  /** 0..1, 계산할 수 없으면 null */
  weight: number | null;
};

export type PortfolioValuation = {
  calculatedAt: string;
  currency: string | null;
  totalMarketValue: number | null;
  weightStatus: 'available' | 'unavailable';
  weightUnavailableCode:
    'missing_price' | 'mixed_currency' | 'zero_total' | null;
  weightUnavailableReason: string | null;
};

export type Portfolio = {
  connected: boolean;
  connection: PortfolioConnection | null;
  holdings: Holding[];
  mockAsOf: string | null;
  valuation: PortfolioValuation | null;
};

/** 계좌 연결 화면에 들어온 곳. 초기 설정(D-ONB-02)과 내 종목(D-MY-01)을 구분한다. */
export type PortfolioConnectSource = 'onboarding' | 'my';

export type PortfolioConnectProps = {
  source: PortfolioConnectSource;
  /** 초기 설정: 이전 단계(투자 여부). 내 종목: 취소·뒤로 → 내 종목 */
  onBack: () => void;
  /** 연결 성공 직후. 내 종목은 여기서 돌아간다. */
  onConnected?: (connection: PortfolioConnection) => void;
  /** 초기 설정: 건너뛰기·[관심 종목 고르기] */
  onContinue?: () => void;
};
