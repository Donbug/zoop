import { call } from '@/apis/auth/ApiService';
import type { CompanyBrief, CompanySummary } from '@/types/company';

// 목표 계약(docs/api/openapi.yaml)의 응답은 ApiResponse로 감싸지 않은 본문 그대로다.
// 공통 call()은 실패 시 상태 문구만 담은 Error를 던지므로 오류 코드를 구분하지 않는다.

const COMPANIES_API = '/api/v1/companies';
const SEARCH_LIMIT = 20;

/** CompanyListResponse. metadata는 화면에서 쓰지 않아 생략한다. */
type CompanyListResponse = {
  items: CompanySummary[];
  nextCursor: string | null;
};

/** 기업명·별칭·종목 코드로 명시적 검색. 첫 페이지(limit 20)만 쓴다. */
export function searchCompanies(query: string): Promise<CompanyListResponse> {
  const params = new URLSearchParams({
    q: query,
    limit: String(SEARCH_LIMIT),
  });
  return call<CompanyListResponse>(`${COMPANIES_API}?${params}`, 'GET');
}

/** CompanyDetail 중 관심 종목 행에 쓰는 값만. metadata 등 나머지는 생략한다. */
type CompanyDetailResponse = {
  id: string;
  name: string;
  ticker: string | null;
  directIssues: { issueId: string }[];
  structuralIssues: { issueId: string }[];
};

/**
 * 관심 종목 행 표시용 기업 요약.
 * 승인된 사건 수는 직접·구조 관련 사건을 issueId 기준으로 한 번씩 센다
 * (검색 결과 issueCount와 같은 기준으로 가정).
 */
export async function getCompanyBrief(id: string): Promise<CompanyBrief> {
  const detail = await call<CompanyDetailResponse>(
    `${COMPANIES_API}/${encodeURIComponent(id)}`,
    'GET',
  );
  const issueIds = new Set(
    [...detail.directIssues, ...detail.structuralIssues].map(
      (issue) => issue.issueId,
    ),
  );
  return {
    id: detail.id,
    name: detail.name,
    ticker: detail.ticker,
    issueCount: issueIds.size,
  };
}
