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

  it('D-GRP-03 선택한 기업을 보유하지 않으면 가상 계좌 보유 영역을 숨긴다', () => {
    renderPanel('member-token');
    expect(
      screen.queryByRole('heading', { name: '가상 계좌 보유' }),
    ).toBeNull();
  });

  it('D-GRP-03 선택한 기업을 보유하면 가상 계좌 보유 영역을 표시한다', () => {
    vi.mocked(useCompanyData).mockReturnValue({
      ...state,
      data: {
        ...state.data,
        holding: {
          companyId: company.id,
          name: company.name,
          ticker: company.ticker,
          quantity: 20,
          avgPrice: 60000,
          avgPriceCurrency: 'KRW',
          marketValue: 1200000,
          weight: 0.5,
        },
      },
    });
    renderPanel('member-token');
    expect(
      screen.getByRole('heading', { name: '가상 계좌 보유' }),
    ).toBeTruthy();
    expect(screen.getByText('20주')).toBeTruthy();
  });

  it('D-GRP-03 다른 종목만 보유 중이면 선택 기업의 보유 영역을 숨긴다', () => {
    vi.mocked(useCompanyData).mockReturnValue({
      ...state,
      data: { ...state.data, holding: null },
    });
    renderPanel('member-token');
    expect(
      screen.queryByRole('heading', { name: '가상 계좌 보유' }),
    ).toBeNull();
    expect(
      screen.queryByText('이 기업의 모의 보유 내역이 없습니다.'),
    ).toBeNull();
  });

  it('D-GRP-03 보유 비중을 계산할 수 없으면 대시로 표시한다', () => {
    vi.mocked(useCompanyData).mockReturnValue({
      ...state,
      data: {
        ...state.data,
        holding: {
          companyId: company.id,
          name: company.name,
          ticker: company.ticker,
          quantity: 20,
          avgPrice: 60000,
          avgPriceCurrency: 'KRW',
          marketValue: null,
          weight: null,
        },
      },
    });
    renderPanel('member-token');
    expect(screen.getByText('-', { selector: 'b' })).toBeTruthy();
    expect(screen.queryByText('통화 혼합으로 계산 안 함')).toBeNull();
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

  // #388 리뷰: 사이드바와 기업 상세는 같은 관심 목록을 본다.
  it('FS027 저장한 관심 목록을 지도 화면에 알리고, 사이드바에서 바꾼 목록을 ★에 반영한다', async () => {
    vi.mocked(setWatchlistCompany).mockResolvedValue({
      watchlistIds: [company.id],
      version: 2,
    } as never);
    const onWatchSaved = vi.fn();
    const panel = (watchSync: { ids: string[]; seq: number } | null) => (
      <MemoryRouter>
        <CompanyDetailPanel
          companyId={company.id}
          fallback={fallback}
          relatedCompanies={[]}
          token="member-token"
          watchSync={watchSync}
          onWatchSaved={onWatchSaved}
          onClose={vi.fn()}
          onSelectIssue={vi.fn()}
          onFocus={vi.fn()}
          onAskAi={vi.fn()}
        />
      </MemoryRouter>
    );
    const { rerender } = render(panel(null));
    await userEvent.click(screen.getByRole('button', { name: '☆ 관심 추가' }));
    await screen.findByRole('button', { name: '★ 관심 해제' });
    expect(onWatchSaved).toHaveBeenCalledWith([company.id]);

    rerender(panel({ ids: [], seq: 1 }));
    expect(screen.getByRole('button', { name: '☆ 관심 추가' })).toBeTruthy();
    rerender(panel({ ids: [company.id], seq: 2 }));
    expect(screen.getByRole('button', { name: '★ 관심 해제' })).toBeTruthy();
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

  it('D-GRP-03 관련 기업이 5곳보다 많으면 나머지를 접어 두고 펼쳐서 고를 수 있다', async () => {
    const onSelectRelation = vi.fn();
    const related = Array.from({ length: 7 }, (_, i) => ({
      id: `KRX:00000${i}`,
      name: `합성 기업 ${i + 1}`,
      sharedIssueCount: 1,
    }));
    render(
      <MemoryRouter>
        <CompanyDetailPanel
          companyId={company.id}
          fallback={fallback}
          relatedCompanies={related}
          token={null}
          onClose={vi.fn()}
          onSelectIssue={vi.fn()}
          onFocus={vi.fn()}
          onAskAi={vi.fn()}
          onSelectRelation={onSelectRelation}
        />
      </MemoryRouter>,
    );
    const more = screen.getByText('관련 기업 2곳 더 보기');
    const hidden = screen.getByRole('button', {
      name: /합성 기업 7/,
      hidden: true,
    });
    expect(more.closest('details')!.open).toBe(false);
    expect(more.closest('details')!.contains(hidden)).toBe(true);
    await userEvent.click(more);
    await userEvent.click(screen.getByRole('button', { name: /합성 기업 7/ }));
    expect(onSelectRelation).toHaveBeenCalledWith('KRX:000006');
  });

  it('D-GRP-03 N-e 직접 이슈의 정확한 시각은 KST로, 날짜만 있는 값은 그대로 보인다', () => {
    const [first, second] = company.directIssues;
    vi.mocked(useCompanyData).mockReturnValue({
      ...state,
      data: {
        ...state.data,
        company: {
          ...company,
          directIssues: [
            { ...first, eventTime: '2026-10-08T00:30:00Z' },
            { ...second, eventTime: '2026-10-07' },
          ],
        },
      },
    });
    renderPanel();
    expect(screen.getByText(/2026-10-08 09:30 KST · 근거/)).toBeTruthy();
    expect(screen.getByText(/^2026-10-07 · 근거/)).toBeTruthy();
    expect(screen.queryByText(/2026-10-08T00:30:00Z/)).toBeNull();
  });

  it('D-GRP-03 N-e 직접 이슈 시각은 받은 정밀도까지만 보인다', () => {
    const [first, second] = company.directIssues;
    vi.mocked(useCompanyData).mockReturnValue({
      ...state,
      data: {
        ...state.data,
        company: {
          ...company,
          directIssues: [
            {
              ...first,
              eventTime: '2026-01-01T00:00:00+09:00',
              timePrecision: 'year',
            },
            { ...second, eventTime: null, timePrecision: 'unknown' },
          ],
        },
      },
    });
    renderPanel();
    expect(screen.getByText(/^2026 · 근거/)).toBeTruthy();
    expect(screen.queryByText(/00:00 KST/)).toBeNull();
    expect(screen.getByText(/^시각 미상 · 근거/)).toBeTruthy();
  });
});
