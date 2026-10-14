import { call } from '@/apis/auth/ApiService';
import { getCsrfToken } from '@/apis/auth/auth';
import type { ApiResponse } from '@/apis/commonType';
import type {
  CompanyDetail,
  CompanyDocumentsResponse,
  CompanyMetrics,
  CompanyQuote,
  PortfolioResponse,
  PriceSeries,
  SettingsResponse,
} from '@/types/map/company';

export const usesCompanyMock =
  import.meta.env.DEV && import.meta.env.VITE_GRAPH_DATA_SOURCE !== 'api';

async function fixture<T>(loader: () => T): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, 120));
  return loader();
}

async function read<T>(url: string): Promise<T> {
  const response = await call<ApiResponse<T>>(url, 'GET', undefined, {
    skipAuth: true,
  });
  return response.data;
}

export const companyUrl = (id: string) =>
  `/api/v1/companies/${encodeURIComponent(id)}`;

export async function getCompany(id: string): Promise<CompanyDetail> {
  if (usesCompanyMock)
    return fixture(async () =>
      (await import('@/mocks/company/fixture')).mockCompany(id),
    );
  return read(companyUrl(id));
}

export async function getCompanyQuote(id: string): Promise<CompanyQuote> {
  if (usesCompanyMock)
    return fixture(async () =>
      (await import('@/mocks/company/fixture')).mockQuote(id),
    );
  return read(`${companyUrl(id)}/quote`);
}

export async function getCompanyMetrics(id: string): Promise<CompanyMetrics> {
  if (usesCompanyMock)
    return fixture(async () =>
      (await import('@/mocks/company/fixture')).mockMetrics(id),
    );
  return read(`${companyUrl(id)}/metrics`);
}

export async function getCompanyPrices(id: string): Promise<PriceSeries> {
  if (usesCompanyMock)
    return fixture(async () =>
      (await import('@/mocks/company/fixture')).mockPrices(id),
    );
  return read(`${companyUrl(id)}/prices?period=1m`);
}

export async function getCompanyDocuments(
  id: string,
): Promise<CompanyDocumentsResponse> {
  if (usesCompanyMock)
    return fixture(async () =>
      (await import('@/mocks/company/fixture')).mockDocuments(id),
    );
  return read(`${companyUrl(id)}/documents?limit=3`);
}

export async function getPortfolio(): Promise<PortfolioResponse> {
  if (usesCompanyMock)
    return fixture(async () =>
      (await import('@/mocks/company/fixture')).mockPortfolio(),
    );
  const response = await call<ApiResponse<PortfolioResponse>>(
    '/api/v1/portfolio',
    'GET',
  );
  return response.data;
}

export async function setWatchlistCompany(
  id: string,
  watched: boolean,
): Promise<SettingsResponse> {
  if (usesCompanyMock)
    return fixture(async () =>
      (await import('@/mocks/company/fixture')).mockSetWatch(id, watched),
    );
  const csrfToken = getCsrfToken();
  if (!csrfToken)
    throw new Error('인증 세션의 CSRF 토큰이 없습니다. 다시 로그인해 주세요.');
  const response = await call<ApiResponse<SettingsResponse>>(
    `/api/v1/me/watchlist/${encodeURIComponent(id)}`,
    'PUT',
    { watched },
    { headers: { 'X-CSRF-Token': csrfToken } },
  );
  return response.data;
}
