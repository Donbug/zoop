import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CompanyDetailPanel from '@/components/graph/CompanyDetailPanel';
import { useCompanyData } from '@/hooks/useCompanyData';
import { useTutorialInteractionLock } from '@/components/graph/tutorial/useTutorialInteractionLock';
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

function RetryLock() {
  useTutorialInteractionLock(3, true);
  return null;
}
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

  it('D-GRP-03 aliases가 있으면 기업명 아래에서 다른 이름을 펼쳐 볼 수 있다', async () => {
    const view = renderPanel();
    const summary = screen.getByText('기업명 더 보기');
    const details = summary.closest('details')!;
    expect(details.open).toBe(false);
    await userEvent.click(summary);
    expect(details.open).toBe(true);
    expect(details.textContent).toContain(company.aliases.join(' · '));
    const header = view.container.querySelector('.company-panel-header')!;
    expect(header.contains(details)).toBe(true);
    expect(
      header.querySelector('h2')!.compareDocumentPosition(details) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      details.compareDocumentPosition(
        header.querySelector('.company-price-row')!,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('D-GRP-03 aliases가 없으면 기업명 더 보기를 표시하지 않는다', () => {
    vi.mocked(useCompanyData).mockReturnValue({
      ...state,
      data: { ...state.data, company: { ...company, aliases: [] } },
    });
    renderPanel();
    expect(screen.queryByText('기업명 더 보기')).toBeNull();
  });

  it('튜토리얼 잠금 중에도 실제 SectionError 재시도가 작동한다', async () => {
    vi.mocked(useCompanyData).mockReturnValue({
      ...state,
      errors: { quote: 'offline' },
    });
    render(<RetryLock />);
    renderPanel();
    const retry = await screen.findByRole('button', { name: '다시 시도' });
    expect((retry as HTMLButtonElement).disabled).toBe(false);
    const calls = vi.mocked(useCompanyData).mock.calls.length;
    await userEvent.click(retry);
    expect(vi.mocked(useCompanyData).mock.calls.length).toBeGreaterThan(calls);
    expect(vi.mocked(useCompanyData).mock.calls.at(-1)?.[2]).toBe(1);
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

  it('D-GRP-03 로고·종목코드·기업명·가격·등락·기준 시각을 머리에 모으고, 거래량 등 중요 정보는 회색 박스에 둔다', () => {
    const view = renderPanel();
    const header = view.container.querySelector('.company-panel-header')!;
    const quote = state.data.quote;
    if (quote.status !== 'available') throw new Error('fixture');
    expect(header.querySelector('h2')!.textContent).toBe(company.name);
    expect(header.textContent).toContain(company.ticker!);
    expect(header.querySelector('.company-price-row')).toBeTruthy();
    expect(header.querySelector('.company-quote-meta')!.textContent).toContain(
      '기준',
    );
    expect(header.querySelector('.company-stat-grid')).toBeNull();
    const box = view.container.querySelector('.company-quote')!;
    expect(box.querySelector('.company-stat-grid')!.textContent).toContain(
      '거래량',
    );
    expect(box.querySelector('.company-price-row')).toBeNull();
  });

  it('D-GRP-03 비회원의 로그인 후 관심 추가는 지금 지도 주소를 로그인 화면에 넘긴다', async () => {
    function LoginProbe() {
      const location = useLocation();
      const from = (
        location.state as { from?: { pathname: string; search: string } }
      )?.from;
      return <p>{`login from ${from?.pathname}${from?.search}`}</p>;
    }
    render(
      <MemoryRouter initialEntries={['/?mode=all&select=node%3AKRX%3A005930']}>
        <Routes>
          <Route
            path="/"
            element={
              <CompanyDetailPanel
                companyId={company.id}
                fallback={fallback}
                relatedCompanies={[]}
                token={null}
                onClose={vi.fn()}
                onSelectIssue={vi.fn()}
                onFocus={vi.fn()}
                onConnections={vi.fn()}
                onAskAi={vi.fn()}
              />
            }
          />
          <Route path="/login" element={<LoginProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(
      screen.getByRole('link', { name: '로그인 후 관심 추가' }),
    );
    expect(
      screen.getByText('login from /?mode=all&select=node%3AKRX%3A005930'),
    ).toBeTruthy();
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
