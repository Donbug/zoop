import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RelationDetailPanel from '@/components/graph/RelationDetailPanel';
import { getRelation } from '@/apis/graph/relations';
import { ApiError } from '@/apis/auth/ApiService';
import { createMockRelation } from '@/mocks/relations/fixture';
import { createMockGraph } from '@/mocks/graph/response';
import type { RelationDetail } from '@/types/map/relation';
import { deferred } from '../support/fakeServer';

vi.mock('@/apis/graph/relations', () => ({ getRelation: vi.fn() }));
const mocked = vi.mocked(getRelation);
const edge = createMockGraph({ mode: 'all', personalFilter: 'all' }).edges.find(
  (item) => item.relationType === 'SHARES_ISSUE',
)!;
const props = {
  id: edge.id,
  context: {},
  onClose: vi.fn(),
  onSelectNode: vi.fn(),
  onAction: vi.fn(),
};
beforeEach(() => {
  vi.clearAllMocks();
  mocked
    .mockReset()
    .mockImplementation(async (id, context) => createMockRelation(id, context));
});

describe('D-GRP-04 · relation rail states', () => {
  it('focuses the loading title and renders endpoints, direction and scoped evidence actions', async () => {
    const pending = deferred<RelationDetail>();
    mocked.mockReturnValueOnce(pending.promise);
    render(<RelationDetailPanel {...props} />);
    expect(screen.getByRole('status').textContent).toContain('불러오는 중');
    expect(document.activeElement).toBe(
      screen.getByRole('heading', { name: '연결선 상세' }),
    );
    const detail = createMockRelation(edge.id);
    await act(async () => pending.resolve(detail));
    expect(screen.getByText('방향 없음')).toBeTruthy();
    expect(screen.getByText('확인 시점 미제공')).toBeTruthy();
    const panel = screen.getByRole('complementary');
    expect(panel.getAttribute('data-screen-id')).toBe('D-GRP-04');
    const buttons = within(panel).getAllByRole('button', {
      name: /근거 .*건 보기/,
    });
    await userEvent.click(buttons[0]);
    expect(props.onAction).toHaveBeenLastCalledWith('evidence', detail);
    await userEvent.click(buttons[1]);
    expect(props.onAction).toHaveBeenLastCalledWith(
      'evidence',
      detail,
      detail.via[0].id,
    );
    await userEvent.click(
      screen.getByRole('button', { name: detail.via[0].title }),
    );
    expect(props.onSelectNode).toHaveBeenCalledWith(detail.via[0].id);
    await userEvent.click(screen.getByRole('button', { name: 'AI에게 묻기' }));
    expect(props.onAction).toHaveBeenLastCalledWith('ai', detail);
    await userEvent.keyboard('{Escape}');
    expect(props.onClose).toHaveBeenCalledOnce();
  });
  it('offers retry for a service failure and recovers', async () => {
    mocked.mockRejectedValueOnce(
      new ApiError(503, 'SOURCE_UNAVAILABLE', '일시적 오류'),
    );
    render(<RelationDetailPanel {...props} />);
    expect((await screen.findByRole('alert')).textContent).toContain(
      '일시적 오류',
    );
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('방향 없음');
    expect(mocked).toHaveBeenCalledTimes(2);
  });
  it('does not retry a permission failure', async () => {
    mocked.mockRejectedValueOnce(
      new ApiError(403, 'ACCESS_DENIED', '권한 없음'),
    );
    render(<RelationDetailPanel {...props} />);
    expect((await screen.findByRole('alert')).textContent).toContain(
      '권한 없음',
    );
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull();
  });
  it.each(['empty', 'no-evidence'] as const)(
    'shows %s without fabricating actionable evidence',
    async (scenario) => {
      mocked.mockResolvedValueOnce(createMockRelation(edge.id, {}, scenario));
      render(<RelationDetailPanel {...props} />);
      await screen.findByText(/연결된 근거가 없습니다/);
      screen
        .getAllByRole('button', { name: '근거 0건 보기' })
        .forEach((button) =>
          expect((button as HTMLButtonElement).disabled).toBe(true),
        );
      if (scenario === 'empty')
        expect(screen.getByText('공유 사건이 없습니다.')).toBeTruthy();
    },
  );
  it('ignores late results and hides old details immediately on context changes', async () => {
    const pending = deferred<RelationDetail>();
    mocked.mockReturnValueOnce(pending.promise);
    const { rerender } = render(<RelationDetailPanel {...props} />);
    rerender(<RelationDetailPanel {...props} id="mock-follows-1" />);
    await screen.findByText('후속 관계');
    await act(async () => pending.resolve(createMockRelation(edge.id)));
    expect(screen.queryByText('방향 없음')).toBeNull();
    rerender(
      <RelationDetailPanel
        {...props}
        id="mock-follows-1"
        context={{ graphVersion: 'missing' }}
      />,
    );
    expect(screen.queryByText('후속 관계')).toBeNull();
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain(
        '최신 데이터로 대체하지 않습니다',
      ),
    );
  });
});
