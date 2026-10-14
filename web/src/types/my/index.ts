import type { ReactNode } from 'react';
import type { AsyncData } from '@/hooks/useAsyncData';
import type { CompanySearchTerms } from '@/types/company';
import type { Portfolio } from '@/types/portfolio';
import type { MemberSettings } from '@/types/settings';

/** 관심 종목 한 건의 추가·해제(PUT /me/watchlist/{id}의 목표 상태) */
export type WatchChange = {
  companyId: string;
  name: string;
  watched: boolean;
};

export type HoldingsSectionProps = {
  portfolio: AsyncData<Portfolio>;
  /** [가상 계좌 연결하기]: 이 화면 안에서 연결 기능을 연다. */
  onConnect: () => void;
};

export type WatchlistSectionProps = {
  settings: AsyncData<MemberSettings>;
  portfolio: AsyncData<Portfolio>;
  /** 검색어는 내 종목 화면이 들고 있어 계좌 연결에 다녀와도 남는다. */
  terms: CompanySearchTerms;
  onTermsChange: (terms: CompanySearchTerms) => void;
};

export type StockRowProps = {
  id: string;
  name: string;
  description?: ReactNode;
  /** 오른쪽 끝 값(예: 시세) */
  trailing?: ReactNode;
  /** 행 밖 오른쪽 행동(예: 관심 종목에서 빼기) */
  action?: ReactNode;
};
