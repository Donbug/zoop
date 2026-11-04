import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useCompanyData } from '@/hooks/useCompanyData';
import * as api from '@/apis/graph/companies';
import {
  mockCompany,
  mockDocuments,
  mockMetrics,
  mockPrices,
  mockQuote,
} from '@/mocks/company/fixture';

vi.mock('@/apis/graph/companies');

describe('useCompanyData', () => {
  beforeEach(() => {
    vi.mocked(api.getCompany).mockResolvedValue(mockCompany('KRX:005930'));
    vi.mocked(api.getCompanyQuote).mockResolvedValue(mockQuote('KRX:005930'));
    vi.mocked(api.getCompanyMetrics).mockResolvedValue(
      mockMetrics('KRX:005930'),
    );
    vi.mocked(api.getCompanyPrices).mockResolvedValue(mockPrices('KRX:005930'));
    vi.mocked(api.getCompanyDocuments).mockResolvedValue(
      mockDocuments('KRX:005930'),
    );
    vi.mocked(api.getPortfolio).mockResolvedValue({
      connected: true,
      mockAsOf: null,
      holdings: [],
    });
  });

  it('한 섹션 실패를 격리하고 정상 섹션을 유지한다', async () => {
    vi.mocked(api.getCompanyMetrics).mockRejectedValue(
      new Error('지표 공급자 장애'),
    );
    const { result } = renderHook(() => useCompanyData('KRX:005930', null));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data?.company.name).toBe('삼성전자');
    expect(result.current.data?.quote.status).toBe('available');
    expect(result.current.errors.metrics).toBe('지표 공급자 장애');
  });

  it('로그인하지 않은 경우 개인 포트폴리오를 요청하지 않는다', async () => {
    const { result } = renderHook(() => useCompanyData('KRX:005930', null));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.getPortfolio).not.toHaveBeenCalled();
    expect(result.current.data?.holding).toBeNull();
  });

  it('다른 기업만 보유한 포트폴리오에서는 선택 기업의 보유 내역을 반환하지 않는다', async () => {
    vi.mocked(api.getPortfolio).mockResolvedValue({
      connected: true,
      mockAsOf: null,
      holdings: [
        {
          companyId: 'KRX:OTHER',
          name: '다른 기업',
          ticker: null,
          quantity: 2,
          avgPrice: 100,
          avgPriceCurrency: null,
          marketValue: null,
          weight: null,
        },
      ],
    });
    const { result } = renderHook(() =>
      useCompanyData('KRX:005930', 'member-token'),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data?.holding).toBeNull();
  });

  it('시세 응답을 기다리지 않고 그래프 응답이 오면 기업 정보를 먼저 반환한다', async () => {
    let resolveQuote: (value: ReturnType<typeof mockQuote>) => void = () => {};
    vi.mocked(api.getCompanyQuote).mockReturnValue(
      new Promise((resolve) => {
        resolveQuote = resolve;
      }),
    );
    const { result } = renderHook(() => useCompanyData('KRX:005930', null));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data?.company.name).toBe('삼성전자');
    expect(result.current.data?.documents).toBeDefined();
    expect(result.current.marketLoading).toBe(true);
    expect(result.current.data?.quote).toBeUndefined();

    resolveQuote(mockQuote('KRX:005930'));
    await waitFor(() => expect(result.current.marketLoading).toBe(false));
    expect(result.current.data?.quote.status).toBe('available');
    expect(result.current.data?.company.name).toBe('삼성전자');
  });

  it('시세 응답이 먼저 와도 그래프 응답 전에는 기업 정보를 반환하지 않는다', async () => {
    let resolveCompany: (
      value: ReturnType<typeof mockCompany>,
    ) => void = () => {};
    vi.mocked(api.getCompany).mockReturnValue(
      new Promise((resolve) => {
        resolveCompany = resolve;
      }),
    );
    const { result } = renderHook(() => useCompanyData('KRX:005930', null));
    await waitFor(() => expect(result.current.marketLoading).toBe(false));
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();

    resolveCompany(mockCompany('KRX:005930'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data?.company.name).toBe('삼성전자');
    expect(result.current.data?.quote.status).toBe('available');
  });

  it('keeps round selectors on documents but leaves latest prices independent', async () => {
    const context = {
      round: 'round-old',
      graphVersion: 'v-old',
      asOf: '2026-10-08T00:20:00Z',
    };
    const { result } = renderHook(() =>
      useCompanyData('KRX:005930', null, 0, context),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.getCompanyDocuments).toHaveBeenCalledWith('KRX:005930', context);
    expect(api.getCompanyQuote).toHaveBeenCalledWith('KRX:005930');
    expect(api.getCompanyPrices).toHaveBeenCalledWith('KRX:005930');
  });
});
