import { create } from 'zustand';
import type { OnboardingDraft, OnboardingState } from '@/types/onboarding';

const initial: OnboardingDraft = {
  investmentStatus: null,
  virtualAccountId: null,
  watchlistIds: [],
};

// 저장 전 초안만 관리한다. 저장된 관심 종목/보유 종목은 서버 상태다.
export const useOnboardingStore = create<OnboardingState>((set) => ({
  ...initial,
  setInvestmentStatus: (investmentStatus) =>
    set({ investmentStatus, virtualAccountId: null }),
  setVirtualAccountId: (virtualAccountId) => set({ virtualAccountId }),
  toggleWatchlist: (id) =>
    set((state) => ({
      watchlistIds: state.watchlistIds.includes(id)
        ? state.watchlistIds.filter((value) => value !== id)
        : [...state.watchlistIds, id],
    })),
  reset: () => set(initial),
}));
