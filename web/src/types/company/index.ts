export type CompanyTab = 'events' | 'documents' | 'info';

export type CompanyTabOption = {
  value: CompanyTab;
  label: string;
};

export type ChartPeriod = '1d' | '1w' | '1m' | '1y' | 'all';

/** GET /api/v1/companies 검색 결과 행(docs/api/openapi.yaml CompanySummary) */
export type CompanySummary = {
  id: string;
  name: string;
  ticker: string | null;
  aliases: string[];
  sector: string | null;
  brandColor: string | null;
  logoUrl: string | null;
  /** 승인된 사건 수 */
  issueCount: number;
};

/** 관심 종목 행에 쓰는 기업 요약. 검색 결과(CompanySummary)나 기업 상세에서 얻는다. */
export type CompanyBrief = Pick<
  CompanySummary,
  'id' | 'name' | 'ticker' | 'issueCount'
>;

/** 입력 중인 검색어(draft)와 마지막으로 실행한 검색어(query) */
export type CompanySearchTerms = {
  draft: string;
  query: string;
};

export type CompanySearchProps = {
  /** 검색창 이름(접근성 이름) */
  label?: string;
  terms: CompanySearchTerms;
  onTermsChange: (terms: CompanySearchTerms) => void;
  /** 이미 고른 기업 id. 행 버튼이 '선택됨'으로 보이고 누르면 해제한다. */
  selectedIds: string[];
  /** 가상 계좌에 있는 기업 id. 행에 '보유' 배지를 붙인다. */
  heldIds?: string[];
  onToggle: (company: CompanySummary) => void;
  /** 저장 중처럼 고르기를 막을 때 */
  disabled?: boolean;
  /** 고르지 않은 행 버튼 이름. 기본 '추가' */
  addLabel?: string;
};
