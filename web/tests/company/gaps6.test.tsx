import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import QuoteSourceHint from '@/components/company/QuoteSourceHint';
import PriceChart from '@/components/company/PriceChart';

const source = {
  provider: 'yahoo',
  name: '합성 출처',
  symbol: 'SYNTH',
  official: false,
  delayNote: null,
  url: 'https://example.com/synthetic',
};
test('D-COM-01 D10 contracted source detail opens by keyboard, Escape returns focus', async () => {
  render(
    <QuoteSourceHint
      source={source}
      derived={[
        'marketCap',
        'not-contract-field',
        'previousClose',
        'fiftyTwoWeekHigh',
      ]}
    />,
  );
  const summary = screen.getByLabelText('시세 출처: 합성 출처');
  summary.focus();
  await userEvent.keyboard('{Enter}');
  expect(summary.closest('details')?.open).toBe(true);
  expect(screen.getByText(/공개 자료 · 종목 기호 SYNTH/)).toBeTruthy();
  expect(screen.getByText(/현재가 × 발행주식수/)).toBeTruthy();
  const link = screen.getByRole('link', { name: '출처에서 확인하기' });
  link.focus();
  await userEvent.keyboard('{Escape}');
  expect(summary.closest('details')?.open).toBe(false);
  expect(document.activeElement).toBe(summary);
});
test.each([null, 'javascript:alert(1)', 'https://name:password@example.com/'])(
  'D-COM-01 D10 unsafe/missing URL %s has no source link',
  (url) => {
    render(<QuoteSourceHint source={{ ...source, url, official: true }} />);
    fireEvent.click(screen.getByLabelText('시세 출처: 합성 출처'));
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText(/공식 시세 API/)).toBeTruthy();
    expect(screen.queryByText(/현재가 ×/)).toBeNull();
  },
);

const points = [
  { time: '2026-10-05T03:00:00Z', close: 0 },
  { time: '2026-10-05T04:00:00Z', close: 120 },
];
test('D-COM-06 D11 mouse/touch show real nearest time and zero close, cancel and replacement clear it', () => {
  vi.stubGlobal('PointerEvent', MouseEvent);
  const onBucket = vi.fn();
  const props = {
    points,
    period: '1d' as const,
    asOf: '2026-10-05T05:00:00Z',
    range: { from: points[0].time, to: points[1].time },
    groups: new Map(),
    selectedBucket: null,
    selectedEvent: null,
    onBucket,
    currency: 'KRW',
  };
  const view = render(<PriceChart {...props} />);
  const chart = screen.getByRole('group', { name: '공급된 종가 차트' });
  vi.spyOn(chart, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    width: 600,
  } as DOMRect);
  fireEvent.pointerMove(chart, { clientX: -10 });
  expect(screen.getByText(/종가 0원/)).toBeTruthy();
  expect(view.container.querySelector('time')?.dateTime).toBe(points[0].time);
  fireEvent.pointerDown(chart, { clientX: 900, pointerType: 'touch' });
  expect(screen.getByText(/종가 120원/)).toBeTruthy();
  fireEvent.click(chart);
  expect(onBucket).not.toHaveBeenCalled();
  fireEvent.pointerCancel(chart);
  expect(screen.queryByText(/종가 120원/)).toBeNull();
  fireEvent.pointerMove(chart, { clientX: 200 });
  fireEvent.pointerLeave(chart);
  expect(view.container.querySelector('time')).toBeNull();
  fireEvent.pointerMove(chart, { clientX: 200 });
  view.rerender(
    <PriceChart {...props} points={[{ ...points[1], close: 20 }]} />,
  );
  expect(view.container.querySelector('time')).toBeNull();
  view.rerender(<PriceChart {...props} points={[]} />);
  expect(screen.getByText('제공된 가격 봉이 없어요.')).toBeTruthy();
});
