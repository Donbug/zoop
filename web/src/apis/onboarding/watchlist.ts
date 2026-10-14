import { call } from '@/apis/auth/ApiService';
import type {
  WatchlistCompany,
  InitialSettings,
  InitialPortfolio,
  CompleteInitialSettings,
} from '@/types/onboarding/watchlist';

export const getInitialSettings = () =>
  call<InitialSettings>('/api/v1/me/settings', 'GET');
export const getInitialPortfolio = () =>
  call<InitialPortfolio>('/api/v1/portfolio', 'GET');
export const searchWatchlistCompanies = (query: string) =>
  call<{ items: WatchlistCompany[]; nextCursor: string | null }>(
    `/api/v1/companies?${new URLSearchParams({ q: query })}`,
    'GET',
    undefined,
    { skipAuth: true },
  );
export const completeInitialSettings = (body: CompleteInitialSettings) =>
  call<InitialSettings>('/api/v1/me/settings', 'PUT', body);
