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
