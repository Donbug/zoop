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
