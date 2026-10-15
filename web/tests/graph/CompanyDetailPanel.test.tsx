import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CompanyDetailPanel from '@/components/graph/CompanyDetailPanel';
import { useCompanyData } from '@/hooks/useCompanyData';
import { setWatchlistCompany } from '@/apis/graph/companies';
import {
  mockCompany,
  mockDocuments,
  mockMetrics,
  mockPrices,
  mockQuote,
} from '@/mocks/company/fixture';

vi.mock('@/hooks/useCompanyData');
vi.mock('@/apis/graph/companies', () => ({ setWatchlistCompany: vi.fn() }));

const company = mockCompany('KRX:005930');
const state = {
  loading: false,
  errors: {},
  data: {
    company,
    quote: mockQuote(company.id),
    metrics: mockMetrics(company.id),
    prices: mockPrices(company.id),
    documents: mockDocuments(company.id),
    holding: null,
  },
};
const fallback = {
  id: company.id,
  kind: 'company' as const,
  label: company.name,
  brandColor: '#1428a0',
  logoUrl: null,
  isFocus: false,
  holding: false,
  watch: false,
  eventTime: null,
  timePrecision: null,
  action: null,
  target: null,
  evidenceCount: null,
  geography: null,
};

function renderPanel(token: string | null = null) {
  return render(
    <MemoryRouter>
      <CompanyDetailPanel
        companyId={company.id}
        fallback={fallback}
        relatedCompanies={[
          { id: 'NASDAQ:NVDA', name: 'NVIDIA', sharedIssueCount: 1 },
        ]}
        token={token}
        onClose={vi.fn()}
        onSelectIssue={vi.fn()}
        onFocus={vi.fn()}
        onConnections={vi.fn()}
        onAskAi={vi.fn()}
      />
    </MemoryRouter>,
  );
}

describe('D-GRP-03 CompanyDetailPanel', () => {
  beforeEach(() => {
    vi.mocked(useCompanyData).mockReturnValue(state);
    vi.mocked(setWatchlistCompany).mockReset();
  });

  it('기업·시세·차트·사건·관련 기업·뉴스 섹션을 표시한다', () => {
    const { container } = renderPanel();
    expect(container.querySelector('[data-screen-id="D-GRP-03"]')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '삼성전자' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '시세' })).toBeTruthy();
    expect(
      screen.getByRole('img', { name: '최근 1개월 가격 추이' }),
    ).toBeTruthy();
    expect(screen.getByText('직접 관련 사건')).toBeTruthy();
    expect(screen.getByText('NVIDIA')).toBeTruthy();
    expect(screen.getByText('뉴스·공시')).toBeTruthy();
  });

  it('관심기업 저장 중 중복 입력을 막고 성공 응답으로 상태를 확정한다', async () => {
    let finish!: (value: { watchlistIds: string[]; version: number }) => void;
    vi.mocked(setWatchlistCompany).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    renderPanel('member-token');
    const user = userEvent.setup();
    const button = screen.getByRole('button', { name: '☆ 관심 추가' });
    await user.click(button);
    expect(
      screen.getByRole('button', { name: '저장 중…' }).hasAttribute('disabled'),
    ).toBe(true);
    await user.click(screen.getByRole('button', { name: '저장 중…' }));
    expect(setWatchlistCompany).toHaveBeenCalledTimes(1);
    finish({ watchlistIds: [company.id], version: 2 });
    expect(
      (await screen.findByRole('button', { name: '★ 관심 해제' })).hasAttribute(
        'disabled',
      ),
    ).toBe(false);
  });

  it('저장 실패 시 관심 상태를 되돌리고 재시도 경로를 제공한다', async () => {
    vi.mocked(setWatchlistCompany).mockRejectedValue(new Error('실패'));
    renderPanel('member-token');
    await userEvent.click(screen.getByRole('button', { name: '☆ 관심 추가' }));
    expect(
      (await screen.findByRole('button', { name: '☆ 관심 추가' })).hasAttribute(
        'disabled',
      ),
    ).toBe(false);
    expect(screen.getByRole('alert').textContent).toContain(
      '관심기업 저장에 실패했습니다',
    );
    expect(
      screen.getByRole('button', { name: '재시도' }).hasAttribute('disabled'),
    ).toBe(false);
  });
});
