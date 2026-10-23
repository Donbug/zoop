import type { EventContext } from '@/types/map/event';
import { snapshotUrl, assertSnapshot } from './snapshot';
import { call } from '@/apis/auth/ApiService';
import { getCsrfToken } from '@/apis/auth/auth';
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

// 목표 계약(docs/api/openapi.yaml)의 응답은 ApiResponse로 감싸지 않은 본문 그대로다.
function read<T>(url: string): Promise<T> {
  return call<T>(url, 'GET', undefined, { skipAuth: true });
}

export const companyUrl = (id: string) =>
  `/api/v1/companies/${encodeURIComponent(id)}`;

export async function getCompany(
  id: string,
  context: EventContext = {},
): Promise<CompanyDetail> {
  if (context.round) {
    const company = await call<
      CompanyDetail & {
        metadata: { graphVersion: string | null; asOf: string };
      }
    >(snapshotUrl(companyUrl(id), context), 'GET', undefined, {
      skipAuth: true,
    });
    if (company.id !== id)
      throw new Error('요청한 기업과 응답이 일치하지 않습니다.');
    assertSnapshot(company.metadata, context);
    return company;
  }
  if (usesCompanyMock)
    return fixture(async () =>
      (await import('@/mocks/company/fixture')).mockCompany(id),
    );
  // 지도가 보여 주는 공개 버전·기준 시점과 같은 기업 관련 사건을 읽는다(#217).
  const company = await read<
    CompanyDetail & {
      metadata?: { graphVersion?: string | null; asOf?: string };
    }
  >(snapshotUrl(companyUrl(id), context));
  if (company.id !== id)
    throw new Error('요청한 기업과 응답이 일치하지 않습니다.');
  // 그래프 버전이 없으면(스냅샷 미게시) 관련 사건 섹션이 실패로 오므로 버전 일치는 확인하지 않는다.
  if (company.metadata?.graphVersion) assertSnapshot(company.metadata, context);
  return company;
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
  context: EventContext = {},
): Promise<CompanyDocumentsResponse> {
  if (context.round) {
    const documents = await read<
      CompanyDocumentsResponse & {
        metadata: { graphVersion: string | null; asOf: string };
      }
    >(snapshotUrl(`${companyUrl(id)}/documents?limit=3`, context));
    assertSnapshot(documents.metadata, context);
    return documents;
  }
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
  return call<PortfolioResponse>('/api/v1/portfolio', 'GET');
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
  return call<SettingsResponse>(
    `/api/v1/me/watchlist/${encodeURIComponent(id)}`,
    'PUT',
    { watched },
    { headers: { 'X-CSRF-Token': csrfToken } },
  );
}
