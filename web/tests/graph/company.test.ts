import { beforeEach, describe, expect, it } from 'vitest';
import {
  mockCompany,
  mockDocuments,
  mockMetrics,
  mockPortfolio,
  mockPrices,
  mockQuote,
  mockSetWatch,
  resetCompanyMock,
} from '@/mocks/company/fixture';
import { companyUrl } from '@/apis/graph/companies';

describe('WBS 6.6.23 · D-GRP-03 기업 상세 목업/API 계약', () => {
  beforeEach(resetCompanyMock);

  it('ERD의 공통 기업 ID로 기업·이슈·보유 데이터를 연결한다', () => {
    const company = mockCompany('KRX:005930');
    expect(company).toMatchObject({
      id: 'KRX:005930',
      name: '삼성전자',
      holding: true,
    });
    expect(
      company.directIssues.every((issue) =>
        issue.issueId.startsWith('mock-issue-'),
      ),
    ).toBe(true);
    expect(
      mockPortfolio().holdings.find(
        (holding) => holding.companyId === company.id,
      ),
    ).toBeDefined();
  });

  it('시세·지표·1개월 일봉에 출처와 통화를 보존한다', () => {
    const quote = mockQuote('KRX:005930');
    const metrics = mockMetrics('KRX:005930');
    const prices = mockPrices('KRX:005930');
    expect(quote.status === 'available' && quote.quote.currency).toBe('KRW');
    expect(
      metrics.status === 'available' && metrics.items.length,
    ).toBeGreaterThan(0);
    expect(prices.status === 'available' && prices.points).toHaveLength(24);
    if (prices.status === 'available') {
      expect(
        prices.points
          .map((point) => Date.parse(point.time))
          .every(Number.isFinite),
      ).toBe(true);
    }
  });

  it('뉴스·공시는 가상 데이터임을 표시하고 원문 링크를 만들지 않는다', () => {
    const documents = mockDocuments('KRX:005930');
    expect(documents.items.length).toBeGreaterThan(0);
    expect(
      documents.items.every(
        (item) => item.url === null && item.title?.includes('(예시)'),
      ),
    ).toBe(true);
  });

  it('관심기업 PUT의 목표 상태를 멱등하게 적용한다', () => {
    expect(mockSetWatch('KRX:005930', true).watchlistIds).toContain(
      'KRX:005930',
    );
    const repeated = mockSetWatch('KRX:005930', true);
    expect(
      repeated.watchlistIds.filter((id) => id === 'KRX:005930'),
    ).toHaveLength(1);
    expect(mockSetWatch('KRX:005930', false).watchlistIds).not.toContain(
      'KRX:005930',
    );
  });

  it('콜론이 있는 기업 ID를 경로에서 인코딩한다', () => {
    expect(companyUrl('KRX:005930')).toBe('/api/v1/companies/KRX%3A005930');
  });
});
