import { create } from 'zustand';
import type { OnboardingDraft, OnboardingState } from '@/types/onboarding';
import type { WatchlistCompany } from '@/types/onboarding/watchlist';

interface WatchlistDraft {
  watchlistOwner: string | null;
  watchlistInitialized: boolean;
  watchlistNames: Record<string, string>;
  searchInput: string;
  searchSubmitted: string | null;
  savingWatchlist: boolean;
  initializeWatchlist: (owner: string, ids: string[]) => void;
  addWatchlistCompany: (company: WatchlistCompany) => void;
  setWatchlistName: (id: string, name: string) => void;
  setSearchInput: (query: string) => void;
  setSearchSubmitted: (query: string) => void;
  setSavingWatchlist: (saving: boolean) => void;
}
const initial: OnboardingDraft &
  Omit<
    WatchlistDraft,
    | 'initializeWatchlist'
    | 'addWatchlistCompany'
    | 'setWatchlistName'
    | 'setSearchInput'
    | 'setSearchSubmitted'
    | 'setSavingWatchlist'
  > = {
  investmentStatus: null,
  virtualAccountId: null,
  watchlistIds: [],
  watchlistOwner: null,
  watchlistInitialized: false,
  watchlistNames: {},
  searchInput: '',
  searchSubmitted: null,
  savingWatchlist: false,
};

// A session-owned, in-memory draft survives step navigation, but not logout or another member.
export const useOnboardingStore = create<OnboardingState & WatchlistDraft>(
  (set) => ({
    ...initial,
    setInvestmentStatus: (investmentStatus) =>
      set({ investmentStatus, virtualAccountId: null }),
    setVirtualAccountId: (virtualAccountId) => set({ virtualAccountId }),
    toggleWatchlist: (id) =>
      set((state) =>
        state.savingWatchlist
          ? state
          : {
              watchlistIds: state.watchlistIds.includes(id)
                ? state.watchlistIds.filter((value) => value !== id)
                : [...state.watchlistIds, id],
            },
      ),
    initializeWatchlist: (owner, ids) =>
      set((state) => {
        if (state.watchlistOwner === owner && state.watchlistInitialized)
          return state;
        return {
          watchlistOwner: owner,
          watchlistInitialized: true,
          watchlistIds: [...new Set(ids)],
          watchlistNames: {},
          searchInput: '',
          searchSubmitted: null,
          savingWatchlist: false,
        };
      }),
    addWatchlistCompany: (company) =>
      set((state) =>
        state.savingWatchlist
          ? state
          : {
              watchlistIds: [...new Set([...state.watchlistIds, company.id])],
              watchlistNames: {
                ...state.watchlistNames,
                [company.id]: company.name,
              },
            },
      ),
    setWatchlistName: (id, name) =>
      set((state) => ({
        watchlistNames: { ...state.watchlistNames, [id]: name },
      })),
    setSearchInput: (searchInput) => set({ searchInput }),
    setSearchSubmitted: (searchSubmitted) => set({ searchSubmitted }),
    setSavingWatchlist: (savingWatchlist) => set({ savingWatchlist }),
    reset: () => set(initial),
  }),
);
