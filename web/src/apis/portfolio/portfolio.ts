import { call } from '@/apis/auth/ApiService';
import type {
  MockPortfolioOption,
  Portfolio,
  PortfolioConnection,
} from '@/types/portfolio';

// 목표 계약(docs/api/openapi.yaml)의 응답은 ApiResponse로 감싸지 않은 본문 그대로다.
// 인증·응답 래퍼 계약이 아직 정해지지 않아 공통 call()을 쓰고 응답 타입만 여기서 정한다.
// call()은 실패 시 상태 문구만 담은 Error를 던지므로 `{ error: { code } }`의 오류 코드
// (예: 이미 연결됨, 연결 없음)를 구분할 수 없다. 화면은 공통 실패 안내와 다시 시도를 보여 준다.

const PORTFOLIO_API = '/api/v1/portfolio';

/** MockPortfolioListResponse. metadata는 화면에서 쓰지 않아 생략한다. */
type MockPortfolioListResponse = {
  items: MockPortfolioOption[];
  nextCursor: string | null;
};

/** ConnectionResponse */
type ConnectionResponse = PortfolioConnection & {
  holdingsCount?: number;
};

/** PortfolioResponse. metadata는 생략한다. */
type PortfolioResponse = Portfolio;

/** 연결할 수 있는 가상 계좌 목록. 첫 페이지만 쓴다(목록이 짧은 모의 데이터). */
export function getMockPortfolios(): Promise<MockPortfolioListResponse> {
  return call<MockPortfolioListResponse>(
    `${PORTFOLIO_API}/mock-portfolios`,
    'GET',
  );
}

/** 지금 연결 상태와 모의 보유 종목 */
export function getPortfolio(): Promise<Portfolio> {
  return call<PortfolioResponse>(PORTFOLIO_API, 'GET');
}

export function connectPortfolio(
  mockPortfolioId: string,
): Promise<ConnectionResponse> {
  return call<ConnectionResponse>(`${PORTFOLIO_API}/connections`, 'POST', {
    mockPortfolioId,
  });
}

/** 204 No Content */
export function disconnectPortfolio(connectionId: string): Promise<void> {
  return call<void>(
    `${PORTFOLIO_API}/connections/${encodeURIComponent(connectionId)}`,
    'DELETE',
  );
}
