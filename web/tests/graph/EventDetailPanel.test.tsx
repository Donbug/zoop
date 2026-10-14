import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import EventDetailPanel from '@/components/graph/EventDetailPanel';
import { getEvent } from '@/apis/graph/events';
import { createMockEvent } from '@/mocks/events/fixture';
import type { EventDetail } from '@/types/map/event';
import { deferred } from '../support/fakeServer';

vi.mock('@/apis/graph/events', async (original) => ({
  ...(await original<typeof import('@/apis/graph/events')>()),
  getEvent: vi.fn(),
}));
const mocked = vi.mocked(getEvent);
const props = {
  id: 'mock-issue-1',
  context: {},
  geography: 'international' as const,
  onClose: vi.fn(),
  onAction: vi.fn(),
};
beforeEach(() => {
  mocked.mockReset();
  props.onClose.mockReset();
  props.onAction.mockReset();
});

describe('D-GRP-02 · panel states and accessibility', () => {
  it('shows a distinct loading state, moves focus, then exposes actions to the keyboard', async () => {
    const pending = deferred<EventDetail>();
    mocked.mockReturnValue(pending.promise);
    render(<EventDetailPanel {...props} />);
    expect(screen.getByRole('status').textContent).toContain('불러오는 중');
    expect(document.activeElement).toBe(
      screen.getByRole('heading', { name: '사건 상세' }),
    );
    const event = createMockEvent(props.id);
    await act(async () => pending.resolve(event));
    expect(screen.getByRole('heading', { name: event.title })).toBeTruthy();
    const user = userEvent.setup();
    await user.tab();
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: '근거 2건 보기' }),
    );
    await user.keyboard('{Enter}');
    expect(props.onAction).toHaveBeenCalledWith('evidence', event);
    await user.keyboard('{Escape}');
    expect(props.onClose).toHaveBeenCalledOnce();
  });
  it('retries a failed selection successfully', async () => {
    mocked
      .mockRejectedValueOnce(new Error('일시적인 오류'))
      .mockResolvedValueOnce(createMockEvent(props.id));
    render(<EventDetailPanel {...props} />);
    expect((await screen.findByRole('alert')).textContent).toContain(
      '일시적인 오류',
    );
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(
      await screen.findByRole('heading', { name: 'HBM4 공급 계약' }),
    ).toBeTruthy();
  });
  it('never lets a late response replace the newest selection', async () => {
    const first = deferred<EventDetail>();
    mocked
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(createMockEvent('mock-issue-2'));
    const { rerender } = render(<EventDetailPanel {...props} />);
    rerender(<EventDetailPanel {...props} id="mock-issue-2" />);
    await screen.findByRole('heading', { name: 'HBM3E 12단 경쟁' });
    await act(async () => first.resolve(createMockEvent(props.id)));
    expect(
      screen.queryByRole('heading', { name: 'HBM4 공급 계약' }),
    ).toBeNull();
  });
  it('hides old details immediately when the pinned context changes', async () => {
    mocked
      .mockResolvedValueOnce(createMockEvent(props.id))
      .mockReturnValueOnce(new Promise(() => {}));
    const { rerender } = render(<EventDetailPanel {...props} />);
    await screen.findByRole('heading', { name: 'HBM4 공급 계약' });
    rerender(
      <EventDetailPanel {...props} context={{ graphVersion: 'other' }} />,
    );
    expect(
      screen.queryByRole('heading', { name: 'HBM4 공급 계약' }),
    ).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('불러오는 중');
  });
  it('distinguishes unknown event time, empty companies, absent evidence and unavailable fields', async () => {
    const event = createMockEvent(props.id, 'no-evidence');
    event.eventTime = null;
    event.timePrecision = 'unknown';
    event.companies = [];
    event.articles[0].title = null;
    event.articles[0].publisher = null;
    mocked.mockResolvedValue(event);
    render(<EventDetailPanel {...props} geography={null} />);
    await screen.findByText('발생 시각 미상');
    expect(screen.getByText('지역 미제공')).toBeTruthy();
    expect(screen.getByText('직접 관련 기업이 없습니다.')).toBeTruthy();
    expect(screen.getByText('연결된 근거가 없습니다.')).toBeTruthy();
    expect(
      (
        screen.getByRole('button', {
          name: '근거 0건 보기',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(screen.getByText(/발행 2026-10-06 09:00 KST/)).toBeTruthy();
    expect(screen.getByText('제목 미제공')).toBeTruthy();
  });
  it('does not count structural links as direct participants or invent confirmed roles', async () => {
    const event = createMockEvent(props.id);
    event.companies[0].roleUnconfirmed = true;
    event.companies[1].relationType = 'STRUCTURALLY_RELATED_TO';
    mocked.mockResolvedValue(event);
    render(<EventDetailPanel {...props} />);
    await screen.findByRole('heading', { name: '직접 관련 기업 2곳' });
    expect(screen.getByText('역할 미확인')).toBeTruthy();
    expect(
      screen.getByRole('heading', { name: '구조적 관련 기업 1곳' }),
    ).toBeTruthy();
  });
  it('shows section failure as failure, never as an empty document list', async () => {
    mocked
      .mockResolvedValueOnce(createMockEvent(props.id, 'partial'))
      .mockResolvedValueOnce(createMockEvent(props.id));
    render(<EventDetailPanel {...props} />);
    await screen.findByText('일부 정보를 불러오지 못했습니다.');
    expect(screen.queryByText('관련 문서가 없습니다.')).toBeNull();
    expect(
      screen.getByRole('heading', { name: '직접 관련 기업 3곳' }),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await waitFor(() =>
      expect(
        within(screen.getByRole('region', { name: '관련 문서 1건' })).getByText(
          '보도 기사',
        ),
      ).toBeTruthy(),
    );
  });
});
