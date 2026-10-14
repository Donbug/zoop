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
// 이미 저장된 관심 종목은 ID만 있으므로 칩에 보일 이름을 기업 상세에서 가져온다.
export const getWatchlistCompanyName = (id: string) =>
  call<{ id: string; name: string }>(
    `/api/v1/companies/${encodeURIComponent(id)}`,
    'GET',
    undefined,
    { skipAuth: true },
  );
export const completeInitialSettings = (body: CompleteInitialSettings) =>
  call<InitialSettings>('/api/v1/me/settings', 'PUT', body);
