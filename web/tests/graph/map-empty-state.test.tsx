import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import MapEmptyState from '@/components/graph/MapEmptyState';
import { createMockGraph } from '@/mocks/graph/response';

it('D-GRP-01b offers account and alternative filters for no personal holdings', async () => {
  const graph = createMockGraph(
    { mode: 'personal', personalFilter: 'holdings' },
    'empty',
  );
  graph.metadata.emptyReason = 'no_personal_stocks';
  graph.metadata.personalFilter = 'holdings';
  const onFilter = vi.fn();
  const onMarket = vi.fn();
  render(
    <MapEmptyState
      graph={graph}
      onPersonalFilter={onFilter}
      onMarket={onMarket}
    />,
  );
  expect(screen.getByText('보유 종목이 없어요.')).toBeTruthy();
  expect(
    screen
      .getByRole('link', { name: '가상 계좌 연결하기' })
      .getAttribute('href'),
  ).toBe('/my');
  await userEvent.click(screen.getByRole('button', { name: '관심으로 보기' }));
  expect(onFilter).toHaveBeenCalledWith('watchlist');
  await userEvent.click(
    screen.getByRole('button', { name: '시장 전체 지도 보기' }),
  );
  expect(onMarket).toHaveBeenCalledOnce();
});

it('names focus companies for no related issues without hiding their nodes', () => {
  const graph = createMockGraph({ mode: 'personal', personalFilter: 'all' });
  graph.edges = [];
  graph.metadata.emptyReason = 'no_related_issues';
  const name = graph.nodes.find(
    (node) => node.kind === 'company' && node.isFocus,
  )!.label;
  render(<MapEmptyState graph={graph} />);
  expect(screen.getByText('내 종목과 연결된 사건이 아직 없어요.')).toBeTruthy();
  expect(screen.getByText(new RegExp(name))).toBeTruthy();
});

it('does not claim a lack of relations when data is partial', () => {
  const graph = createMockGraph(
    { mode: 'personal', personalFilter: 'all' },
    'empty',
  );
  graph.metadata.emptyReason = 'no_personal_stocks';
  graph.metadata.partial = true;
  render(<MapEmptyState graph={graph} />);
  expect(screen.getByText(/일부 자료가 누락되어/)).toBeTruthy();
  expect(screen.queryByText('보유·관심 종목이 없어요.')).toBeNull();
});

it('shows a neutral message for an unknown empty reason', () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  graph.edges = [];
  graph.metadata.emptyReason = 'unknown_from_server';
  render(<MapEmptyState graph={graph} />);
  expect(screen.getByText('현재 지도에 표시된 연결선이 없어요.')).toBeTruthy();
});
