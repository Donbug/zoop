import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import CompanyPathPanel from '@/components/graph/CompanyPathPanel';
import { createMockGraph } from '@/mocks/graph/response';

const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
const props = {
  graph,
  from: 'KRX:005930',
  to: 'NASDAQ:NVDA',
  loading: false,
  error: null,
  onPick: vi.fn(),
  onClose: vi.fn(),
  onRetry: vi.fn(),
  onEvidence: vi.fn(),
};

it('D-GRP-07 does not show a previous successful path while loading or after a failed graph read', async () => {
  const onRetry = vi.fn();
  const { rerender } = render(<CompanyPathPanel {...props} loading />);
  expect(screen.getByRole('status').textContent).toContain('확인하고');
  expect(screen.queryByRole('heading', { name: '2단계 연결' })).toBeNull();
  rerender(
    <CompanyPathPanel {...props} error="temporary failure" onRetry={onRetry} />,
  );
  await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  expect(onRetry).toHaveBeenCalledOnce();
  expect(screen.queryByRole('heading', { name: '2단계 연결' })).toBeNull();
});

it('D-GRP-07 distinguishes an absent path in partial or truncated data from no relationship at all', () => {
  render(
    <CompanyPathPanel
      {...props}
      graph={{
        ...graph,
        edges: [],
        metadata: { ...graph.metadata, partial: true, truncated: true },
      }}
    />,
  );
  const panel = within(
    screen.getByRole('complementary', { name: '두 기업 사이 경로' }),
  );
  expect(panel.getByRole('status').textContent).toContain(
    '조회한 그래프 안에서',
  );
  expect(
    panel.getByText('조회 상한으로 일부 관계가 생략되었습니다.'),
  ).toBeTruthy();
  expect(panel.getByText('일부 자료를 받지 못했습니다.')).toBeTruthy();
});

it('D-GRP-07 displays path context and selects a company from the path', async () => {
  const select = vi.fn();
  render(<CompanyPathPanel {...props} onSelectCompany={select} />);
  expect(screen.getByRole('heading', { name: '2단계 연결' })).toBeTruthy();
  expect(screen.getByLabelText('경로를 찾는 방법')).toBeTruthy();
  await userEvent.click(screen.getByRole('button', { name: '삼성전자' }));
  expect(select).toHaveBeenCalledWith('KRX:005930');
});

it('D-GRP-07 단계 연결선 견본은 지도·범례와 같은 모양이고 방향 화살표를 그리지 않는다', () => {
  const { container } = render(<CompanyPathPanel {...props} />);
  const swatches = [...container.querySelectorAll('ol .legend-line')];
  expect(swatches.length).toBeGreaterThan(0);
  const types = props.graph!.edges.map((edge) => edge.relationType);
  for (const swatch of swatches) {
    if (swatch.classList.contains('dashed'))
      expect(types).toContain('SHARES_ISSUE');
  }
  expect(container.querySelector('ol svg path')).toBeNull();
});
