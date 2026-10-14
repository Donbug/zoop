import type { ReactNode } from 'react';

export type InvestmentStatus = 'investing' | 'not-investing' | null;

export type OnboardingDraft = {
  investmentStatus: InvestmentStatus;
  virtualAccountId: string | null;
  watchlistIds: string[];
};

export type OnboardingState = OnboardingDraft & {
  setInvestmentStatus: (value: InvestmentStatus) => void;
  setVirtualAccountId: (id: string | null) => void;
  toggleWatchlist: (id: string) => void;
  reset: () => void;
};

export type OnboardingStepProps = {
  title: string;
  subtitle?: string;
  /** 없으면 [이전 단계]를 숨긴다. */
  onBack?: () => void;
  /** 저장 중처럼 이전 단계로 가면 안 될 때 */
  backDisabled?: boolean;
  children: ReactNode;
  footer?: ReactNode;
};
